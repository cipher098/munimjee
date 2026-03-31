testMunim fb token = EAARj7Rd0qPYBRBoVQPwxOW1SL44NosXZCh2KRr7s9IodDD5MAjZCSoBgFb3sLK7L46mf7OCSRo6nS23Ne11Czms4zxM9PToRCODyv0lwZAfHugqGGDQSl1W4VgL1S2QHXOfmRB187tKKTuTPzCfwxAzZBi5NBDjzTAHD3mWqZCowoQtYq0sa5RLZB79hggMz2dC4gxr1XAbiKZCAip3ZA4i4whxQjJg6Ogmpz4Ej0nZAzUphTyOyOz1GMQTXHNrsZCPZBHHZCTO4aFlkfKLSL5IF

testMunim page id = 1002203636317376


tcommandf till now 
curl -s -X POST "https://graph.facebook.com/v19.0/1119201497934605/messages" -H "Content-Type: application/json" -H "Authorization: Bearer EAARj7Rd0qPYBRCYx2Y4dluTIxgrJAV7ZBQ8J0yJjQFdKlUoMVB493pZB1flJd6r3aTRZCeis5nKuwqWQvzMzw9z79THE4Ed33wxnE77MS8tROLUb5gZCD9fElQFF3KYtWzsTiLfmvb4KT1VHcSUvDaFZCndZARwB2qtk7fheJpHSg9yJ27uC8fSiMqAMwrDnZABe0pAE8gna1oaV0JU9zDafbpxZBxYwrt3Ac4Ws1TvyeGsZD" -d '{"recipient":{"id":"957282080130744"},"message":{"text":"Test"},"messaging_type":"RESPONSE"}'


{"error":{"message":"(#100) The page is not linked to an Instagram account or the linked IG account is not professional account","type":"OAuthException","code":100,"error_subcode":2534013,"fbtrace_id":"A4ouVAV4yH7rMQdYAA6q5F9"}}%         
  ⎿  ⧉ Selected 1 lines from backend/app/api/webhooks/instagram.py in Visual Studio Code                                                                                                                                               
                                                                                                                                                                                                                                                
⏺ The Facebook Page "testMunim" isn't linked to the Instagram account. Let's link them:                                                                                                                                                         
                                                                                                                                                                                                                                                
  1. Go to facebook.com/1002203636317376 (your testMunim page)                                                                                                                                                                                  
  2. Settings → Linked Accounts or Instagram                                                                                                                                                                                                    
  3. Click Connect Instagram → log in with your Instagram business account                                                                                                                                                                      
                                                                                                                                                                                                                                                
  OR from Instagram side:                                                                                                                                                                                                                       
  1. Instagram app → Settings → Account Center                                                                                                                                                                                                  
  2. Profiles → Add → select the "testMunim" Facebook Page                                                                                                                                                                                      
                                                                                                                                                                                                                                              
  Once linked, the curl will work and we can update the DB with the Page token and Page ID.     


  this worked
  curl -s -X POST "https://graph.facebook.com/v19.0/1119201497934605/messages" -H "Content-Type: application/json" -H "Authorization: Bearer EAARj7Rd0qPYBRCYx2Y4dluTIxgrJAV7ZBQ8J0yJjQFdKlUoMVB493pZB1flJd6r3aTRZCeis5nKuwqWQvzMzw9z79THE4Ed33wxnE77MS8tROLUb5gZCD9fElQFF3KYtWzsTiLfmvb4KT1VHcSUvDaFZCndZARwB2qtk7fheJpHSg9yJ27uC8fSiMqAMwrDnZABe0pAE8gna1oaV0JU9zDafbpxZBxYwrt3Ac4Ws1TvyeGsZD" -d '{"recipient":{"id":"957282080130744"},"message":{"text":"Test"},"messaging_type":"RESPONSE"}'





