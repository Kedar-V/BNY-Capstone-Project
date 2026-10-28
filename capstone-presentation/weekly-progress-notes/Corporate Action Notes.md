# Corporate Action Notes

These examples show that BNY sends two main email formats.

### 1. Corporate Action Notification

```
Corporate Action Notification:
Event ID;
BNY Processing Location;
Security Description;
ISIN;
Corporate Action Type;
Notification Type;
Message ID
```

Example structure:

```
Corporate Action Notification:
Event ID:[EVENT_ID];
[BNYDTC / BNYECL];
[SECURITY_DESCRIPTION];
[ISIN];
[EVENT_TYPE];
[NOTIFICATION_TYPE];
[MESSAGE_ID]
```

Observed corporate action types include:

* `SPIN OFF`
* `CONSENT`
* `EXCHANGE`
* `FULL CALL_EARLY REDEMPTION`
* `FINAL MATURITY`
* `CONVERSION`

Observed notification types include:

* `ANNOUNCEMENT`
* `CANCELLED EVENT NOTIFICATION`
* `REMINDER 1-REMINDER FOR RESPONSE`
* `PAYMENT ADVICE`
* `ACKNOWLEDGEMENT FOR RESPONSE`

### 2. Income Notification

```
Income Notification:
Event ID;
BNY Processing Location;
Security Description;
ISIN;
Income Type;
Notification Type;
Message ID
```

Example:

```
Income Notification:
Event ID:[EVENT_ID];
[BNYDTC];
[SECURITY_DESCRIPTION];
[ISIN];
INTEREST;
DEBIT NOTICE TO CLIENTS;
[MESSAGE_ID]
```

### Important extraction fields

#### Email metadata

* Notification family: Corporate Action or Income
* Sender
* Recipient
* Email date
* Email subject
* Message ID
* Preparation date

#### Event identification

* Event ID
* BNY processing location, such as `BNYDTC` or `BNYECL`
* Notification type
* Notification status
* Processing status
* Mandatory/voluntary indicator

#### Security information

* Security description
* ISIN
* CUSIP, if available
* Ticker, if available
* Currency
* Security type
* Coupon rate
* Maturity date

#### Corporate action information

* Corporate action type
* Event subtype
* Effective date
* Record date
* Ex-date
* Payment date
* Settlement date
* Old security details
* New security details
* Conversion/exchange ratio
* Redemption amount
* Call price
* Consent terms
* Spin-off details

#### Election and response information

* Whether an election is required
* Available options
* Default option
* Election deadline
* Response deadline
* Beneficial-owner deadline
* Instructions for responding
* Reminder number
* Acknowledgment status
* Cancellation or withdrawal reason

#### Position and payment information

* Account number
* Account name
* Eligible quantity
* Position quantity
* Principal amount
* Interest amount
* Redemption amount
* Cash amount
* Currency
* Debit/credit indicator
* Payment calculation details

### Recommended normalized output

```
{
  "notification_family": "",
  "event_id": "",
  "message_id": "",
  "bny_location": "",
  "notification_type": "",
  "notification_status": "",
  "processing_status": "",
  "mandatory_voluntary_indicator": "",
  "preparation_date": "",

  "security_description": "",
  "isin": "",
  "cusip": "",
  "ticker": "",
  "currency": "",
  "coupon_rate": "",
  "maturity_date": "",

  "corporate_action_type": "",
  "income_type": "",
  "event_subtype": "",
  "effective_date": "",
  "record_date": "",
  "ex_date": "",
  "payment_date": "",
  "settlement_date": "",

  "old_security_description": "",
  "old_security_isin": "",
  "new_security_description": "",
  "new_security_isin": "",
  "conversion_ratio": "",
  "conversion_price": "",
  "redemption_amount": "",
  "call_price": "",

  "election_required": "",
  "available_options": [],
  "default_option": "",
  "election_deadline": "",
  "response_deadline": "",
  "reminder_number": "",
  "cancellation_reason": "",

  "account_number": "",
  "account_name": "",
  "eligible_quantity": "",
  "position_quantity": "",
  "principal_amount": "",
  "interest_amount": "",
  "cash_amount": "",
  "debit_credit_indicator": "",

  "sender": "",
  "recipient": "",
  "email_date": "",
  "email_subject": ""
}
```

The most important design choice is to keep `notification_family`, `corporate_action_type`, `income_type`, and `notification_type` as separate fields because BNY uses the same email structure for very different event workflows.


Below is a practical definition of each field for your extraction schema.

### Email and notification metadata

| Field                           | Description                                                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| notification\_family            | Broad category of the email: Corporate Action Notification or Income Notification. Extract from the subject prefix.                   |
| event\_id                       | Unique identifier for the corporate action or income event. Usually appears after Event ID: in the subject and body.                  |
| message\_id                     | Unique identifier for the specific BNY notification message, usually the last value in the subject.                                   |
| bny\_location                   | BNY processing location shown in the subject, such as BNYDTC or BNYECL.                                                               |
| notification\_type              | Purpose of the notification, such as ANNOUNCEMENT, PAYMENT ADVICE, REMINDER 1-REMINDER FOR RESPONSE, or CANCELLED EVENT NOTIFICATION. |
| notification\_status            | Status of the notification or event, such as REPLACEMENT, WITHDRAWAL, CONFIRMED, or CANCELLED.                                        |
| processing\_status              | Processing state, such as Confirmed and Complete or Unconfirmed and Incomplete.                                                       |
| mandatory\_voluntary\_indicator | Whether participation is required or optional: Mandatory or Voluntary.                                                                |
| preparation\_date               | Date and time when BNY prepared the notification.                                                                                     |
| sender                          | Email address sending the notification, for example BaNCS@bny.com.                                                                    |
| recipient                       | Email address receiving the notification.                                                                                             |
| email\_date                     | Date and time from the email header.                                                                                                  |
| email\_subject                  | Complete original subject line.                                                                                                       |

### Security fields

| Field                 | Description                                                                                               |
| --------------------- | --------------------------------------------------------------------------------------------------------- |
| security\_description | Name and description of the security, including issuer, coupon, maturity, and offering type when present. |
| isin                  | International Securities Identification Number, such as US07556QBV68.                                     |
| cusip                 | Nine-character North American security identifier, if provided.                                           |
| ticker                | Trading symbol of the security, if provided.                                                              |
| currency              | Currency associated with the security or payment, such as USD, EUR, or INR.                               |
| coupon\_rate          | Interest/coupon percentage for a debt instrument, such as 7.875%.                                         |
| maturity\_date        | Date when the bond or instrument matures. It may also be included in the security description.            |

### Event classification

| Field                   | Description                                                                                                           |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------- |
| corporate\_action\_type | Main corporate action, such as SPIN OFF, CONSENT, EXCHANGE, CONVERSION, FULL CALL, or FINAL MATURITY.                 |
| income\_type            | Income event type, such as INTEREST, DIVIDEND, or PRINCIPAL. Use this primarily for Income Notifications.             |
| event\_subtype          | More specific description of the action, such as EARLY REDEMPTION, REMINDER FOR RESPONSE, or DEBIT NOTICE TO CLIENTS. |

### Important event dates

| Field            | Description                                                              |
| ---------------- | ------------------------------------------------------------------------ |
| effective\_date  | Date on which the corporate action becomes effective.                    |
| record\_date     | Date used to determine which holders are eligible for the event.         |
| ex\_date         | Date from which the security trades without entitlement to the event.    |
| payment\_date    | Date when cash, securities, interest, or other entitlement is delivered. |
| settlement\_date | Date when the transaction or exchange settles.                           |

These fields may not be present in every notification. The model should return `null` when unavailable rather than infer them.

### Conversion, exchange, and spin-off fields

| Field                      | Description                                                                   |
| -------------------------- | ----------------------------------------------------------------------------- |
| old\_security\_description | Description of the original security before conversion or exchange.           |
| old\_security\_isin        | ISIN of the original security.                                                |
| new\_security\_description | Description of the security received after conversion, exchange, or spin-off. |
| new\_security\_isin        | ISIN of the new security received.                                            |
| conversion\_ratio          | Number of new securities received for each old security.                      |
| conversion\_price          | Price used to calculate the conversion or exchange.                           |
| redemption\_amount         | Amount paid when securities are redeemed or mature.                           |
| call\_price                | Price paid by the issuer for an early/full call.                              |

### Election and response fields

| Field                | Description                                               |
| -------------------- | --------------------------------------------------------- |
| election\_required   | Whether the holder must choose an option.                 |
| available\_options   | All options available to the holder. Store as a list.     |
| default\_option      | Option automatically applied if no election is submitted. |
| election\_deadline   | Deadline for submitting an election.                      |
| response\_deadline   | Deadline for responding to a consent or other event.      |
| reminder\_number     | Reminder sequence, such as 1 for REMINDER 1.              |
| cancellation\_reason | Reason an event was cancelled, withdrawn, or replaced.    |

### Position and payment fields

| Field                    | Description                                                   |
| ------------------------ | ------------------------------------------------------------- |
| account\_number          | Account or portfolio number associated with the notification. |
| account\_name            | Name of the account, fund, or client.                         |
| eligible\_quantity       | Quantity eligible for the corporate action or income payment. |
| position\_quantity       | Quantity held in the account at the relevant date.            |
| principal\_amount        | Principal amount associated with the position or payment.     |
| interest\_amount         | Interest amount paid, received, or debited.                   |
| cash\_amount             | Cash amount associated with the event.                        |
| debit\_credit\_indicator | Whether the amount is a Debit or Credit.                      |

### Recommended handling rules

* Extract values from the body first; use the subject as a fallback.
* Preserve the original text for fields such as `security_description` and `notification_type`.
* Normalize dates to `YYYY-MM-DD` where possible.
* Normalize monetary values to numeric values and retain the currency separately.
* Use `null` for missing fields.
* Use an empty list only for missing list fields such as `available_options`.
* Do not treat `notification_type` as the same thing as `corporate_action_type`.
* A `CANCELLED EVENT NOTIFICATION` or `WITHDRAWAL` should update or cancel an earlier event using the same `event_id`.
