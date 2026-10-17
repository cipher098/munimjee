# Checkout session examples

`session-read.json` is a synthetic DTO example. Its token has JWT syntax only and grants no authority; key/provider IDs are synthetic. Real session tokens are issued by the server after exact provider-order verification and must stay ephemeral in memory, outside SDK options/notes, URLs and storage.

`state-read.json` demonstrates an uncertain provider-order attempt. It must not cause a new provider POST or a fresh commerce order. Only the existing protected reconciliation flow can associate a verified provider order with that attempt.

The strict JSON schemas freeze the public allowlists; secret credentials, seller roles and native session data are not fields in these contracts.

`payment-review.json` and its schema freeze `payment-review.v1`, the native operator-only read contract. Current `orders.write` and a native session are required. No customer order bearer, session capability or gateway credential is included; reconciliation remains an explicit existing protected command.
