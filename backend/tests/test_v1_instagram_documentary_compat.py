"""Synthetic documentary shapes only; never configured-version or live grants."""
import pytest
from app.v1.imports.instagram_owned import OwnedInstagramError
from tests.test_v1_instagram_owned_provider import ACCOUNT,media,response,provider,fetch,PNG


@pytest.mark.asyncio
@pytest.mark.parametrize('wrapper',[False,True])
@pytest.mark.parametrize('account_type',['BUSINESS','CREATOR','MEDIA_CREATOR'])
async def test_single_exact_bound_professional_principal(wrapper,account_type):
    principal={'user_id':ACCOUNT,'account_type':account_type}
    if wrapper:principal={'data':[principal]}
    subject,transport=provider([response(principal),response({'data':[media()]}),response(body=PNG,mime='image/png')])
    result=await fetch(subject)
    assert result.account_id==ACCOUNT and len(transport.calls)==3


@pytest.mark.asyncio
@pytest.mark.parametrize('principal',[
    {'data':[]},{'data':[{'user_id':ACCOUNT,'account_type':'BUSINESS'}]*2},
    {'data':{'user_id':ACCOUNT,'account_type':'BUSINESS'}},
    {'data':[{'user_id':ACCOUNT,'account_type':'BUSINESS'}],'user_id':'999'},
    {'data':[{'user_id':ACCOUNT,'account_type':'BUSINESS'}],'account_type':'PERSONAL'},
    {'data':[{'user_id':'999','account_type':'BUSINESS'}]},
    {'data':[{'user_id':ACCOUNT,'account_type':'BUSINESS','data':[{'user_id':'999'}]}]},
    {'user_id':ACCOUNT,'id':'999','account_type':'BUSINESS'},
    {'user_id':ACCOUNT,'account_type':'Media_Creator'},
    {'user_id':ACCOUNT,'account_type':'Business'},
    {'user_id':ACCOUNT,'account_type':['BUSINESS']},
    {'user_id':ACCOUNT},
])
async def test_ambiguous_mixed_unknown_or_incomplete_principal_never_reads_edge(principal):
    subject,transport=provider([response(principal)])
    with pytest.raises(OwnedInstagramError):await fetch(subject)
    assert len(transport.calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['IMAGE','VIDEO'])
async def test_missing_owned_original_has_truthful_bounded_error_no_cdn(kind):
    item=media();item['media_type']=kind;item.pop('media_url')
    subject,transport=provider([response({'user_id':ACCOUNT,'account_type':'BUSINESS'}),response({'data':[item]})])
    with pytest.raises(OwnedInstagramError,match='instagram_original_unavailable'):await fetch(subject)
    assert len(transport.calls)==2


@pytest.mark.asyncio
async def test_graph_error_does_not_claim_expired_credentials_or_echo_provider_body():
    subject,transport=provider([response({'error':{'message':'synthetic-sensitive-provider-text','code':123}})])
    with pytest.raises(OwnedInstagramError,match='instagram_api_error') as error:await fetch(subject)
    assert 'sensitive' not in str(error.value) and len(transport.calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('tail',[None,{'id':'malformed'},{'id':'67890','media_type':'VIDEO','media_url':'https://scontent.cdninstagram.com/conflicting.mp4'}])
async def test_complete_matched_page_is_validated_before_any_original_fetch(tail):
    subject,transport=provider([response({'user_id':ACCOUNT,'account_type':'BUSINESS'}),response({'data':[media(),tail]}),response(body=PNG,mime='image/png')])
    with pytest.raises(OwnedInstagramError,match='instagram_response_invalid'):await fetch(subject)
    assert len(transport.calls)==2
