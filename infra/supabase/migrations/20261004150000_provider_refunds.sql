-- Refunds say what actually happened to the money.
--
-- kind = 'recorded': the owner gave the money back themselves (cash, UPI, bank,
--   their own card terminal) and recorded it — LOCAH moved no money.
-- kind = 'provider': LOCAH asked the payment provider to send it back. It is
--   'requested' while the call is made, 'processing' once the provider accepts
--   it (with the provider's refund reference), and 'succeeded' or 'failed' when
--   the provider reports the outcome (refund webhooks, applied through the
--   durable webhook pipeline). A failed provider refund releases its amount.

ALTER TABLE payments_refunds
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'recorded' CHECK (kind IN ('recorded', 'provider')),
    ADD COLUMN completed_at TIMESTAMPTZ;

ALTER TABLE payments_refunds DROP CONSTRAINT IF EXISTS payments_refunds_status_check;
ALTER TABLE payments_refunds ADD CONSTRAINT payments_refunds_status_check
    CHECK (status IN ('pending', 'requested', 'processing', 'succeeded', 'failed'));

CREATE INDEX idx_payments_refunds_provider_ref ON payments_refunds (provider_reference)
    WHERE provider_reference IS NOT NULL;

-- Existing refunds were recorded by the owner; they completed when recorded.
UPDATE payments_refunds SET completed_at = created_at WHERE status = 'succeeded' AND completed_at IS NULL;

-- The owner sees a provider refund that failed, until they act on it.
ALTER TABLE payments_payment_attempts DROP CONSTRAINT IF EXISTS payments_payment_attempts_attention_check;
ALTER TABLE payments_payment_attempts ADD CONSTRAINT payments_payment_attempts_attention_check
    CHECK (attention IS NULL OR attention IN ('paid_twice', 'not_received', 'refund_due', 'provider_update_failed',
                                              'refund_failed'));
