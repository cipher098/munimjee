"""Read-only canonical order cohorts. All projections share one PostgreSQL snapshot."""
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import text
from app.schemas.analytics_v1 import AnalyticsRead, Filters

# No credentials/customer/provider identifiers leave PostgreSQL. Only a boolean
# captured association and the historical mode classification enter this CTE.
REPORT = text('''
WITH scoped AS (
 SELECT id, created_at, currency, total, payment_method, payment_status, fulfillment_status,
  NULLIF(gateway_payment_id,'') IS NOT NULL AS captured,
  CASE WHEN payment_method='razorpay' AND gateway_credentials->>'mode'='test' THEN 'known_gateway_test'
       WHEN payment_method='razorpay' AND gateway_credentials->>'mode'='live' THEN 'known_gateway_live'
       ELSE 'unclassified' END AS test_classification
 FROM commerce_orders
 WHERE seller_id=CAST(:business_id AS uuid)
 AND created_at>=CAST(:start_at AS timestamptz) AND created_at<CAST(:end_at AS timestamptz)
 AND (CAST(:payment_status AS text) IS NULL OR payment_status=CAST(:payment_status AS text))
 AND (CAST(:fulfillment_status AS text) IS NULL OR fulfillment_status=CAST(:fulfillment_status AS text))
 AND (CAST(:payment_method AS text) IS NULL OR payment_method=CAST(:payment_method AS text))
), cohort AS (
 SELECT * FROM scoped WHERE CAST(:include_gateway_test AS boolean) OR test_classification<>'known_gateway_test'
), money AS (
 SELECT currency, SUM(total)::text AS placed_order_value_minor,
  COALESCE(SUM(total) FILTER(WHERE payment_method='razorpay' AND payment_status='paid' AND captured),0)::text AS online_paid_minor,
  COALESCE(SUM(total) FILTER(WHERE payment_method='cod' AND payment_status='collected'),0)::text AS cod_collected_minor,
  COALESCE(SUM(total) FILTER(WHERE payment_method='razorpay' AND payment_status='review_required' AND captured),0)::text AS captured_review_minor
 FROM cohort GROUP BY currency
), daily AS (
 SELECT (created_at AT TIME ZONE 'UTC')::date AS date, COUNT(*) AS placed,
 COUNT(*) FILTER(WHERE fulfillment_status='cancelled' OR payment_status='cancelled') AS cancelled
 FROM cohort GROUP BY 1
), ordered AS (
 SELECT id AS order_id,created_at,currency,total::text AS total_minor,payment_method,payment_status,fulfillment_status,test_classification
 FROM cohort ORDER BY created_at DESC,id DESC LIMIT :limit OFFSET :offset
)
SELECT jsonb_build_object(
 'generated_at',statement_timestamp(),
 'counts',(SELECT jsonb_build_object('placed',COUNT(*),
   'online_paid',COUNT(*) FILTER(WHERE payment_method='razorpay' AND payment_status='paid' AND captured),
   'cod_collected',COUNT(*) FILTER(WHERE payment_method='cod' AND payment_status='collected'),
   'payment_review',COUNT(*) FILTER(WHERE payment_status='review_required'),
   'cancelled',COUNT(*) FILTER(WHERE fulfillment_status='cancelled' OR payment_status='cancelled'),
   'expired',COUNT(*) FILTER(WHERE payment_status='expired'),
   'unclassified_test_activity',COUNT(*) FILTER(WHERE test_classification='unclassified')) FROM cohort),
 'currency_totals',COALESCE((SELECT jsonb_agg(to_jsonb(money) ORDER BY currency) FROM money),'[]'::jsonb),
 'daily',COALESCE((SELECT jsonb_agg(to_jsonb(daily) ORDER BY date) FROM daily),'[]'::jsonb),
 'orders',COALESCE((SELECT jsonb_agg(to_jsonb(ordered) ORDER BY created_at DESC,order_id DESC) FROM ordered),'[]'::jsonb),
 'has_next',(SELECT COUNT(*)>:offset+:limit FROM cohort),
 'known_gateway_test_excluded',(SELECT COUNT(*) FROM scoped WHERE NOT CAST(:include_gateway_test AS boolean) AND test_classification='known_gateway_test')
)
''')


async def report(db,business_id,filters: Filters):
    start=datetime.combine(filters.from_date,time.min,tzinfo=timezone.utc)
    end=datetime.combine(filters.to_date,time.min,tzinfo=timezone.utc)
    data=await db.scalar(REPORT,dict(business_id=business_id,start_at=start,end_at=end,
        payment_status=filters.payment_status,fulfillment_status=filters.fulfillment_status,
        payment_method=filters.payment_method,include_gateway_test=filters.include_gateway_test,
        limit=filters.page_size,offset=(filters.page-1)*filters.page_size))
    days={row['date']:row for row in data['daily']}
    data['daily']=[days.get((filters.from_date+timedelta(days=i)).isoformat(),
        {'date':filters.from_date+timedelta(days=i),'placed':0,'cancelled':0})
        for i in range((filters.to_date-filters.from_date).days)]
    return AnalyticsRead(business_id=business_id,filters=filters,**data)
