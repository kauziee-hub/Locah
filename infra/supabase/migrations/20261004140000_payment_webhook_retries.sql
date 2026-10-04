-- Payment webhooks are kept, retried and, at worst, dead-lettered — never lost.
--
-- Before: a webhook whose business effect failed was rolled back with the
-- request, receipt and all; the provider's own retries were the only recovery
-- and nothing was visible. Now the verified receipt is committed first and
-- answered 200; applying it is retried with backoff (attempt_count,
-- next_attempt_at) by the worker; after max_attempts it is dead-lettered
-- (platform_dead_letter_events, shown on the admin System page) and the
-- payment, when known, is flagged for the owner.

ALTER TABLE payments_webhook_receipts
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 8,
    ADD COLUMN next_attempt_at TIMESTAMPTZ,
    ADD COLUMN last_error TEXT,
    ADD COLUMN dead_lettered_at TIMESTAMPTZ,
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE payments_webhook_receipts DROP CONSTRAINT IF EXISTS payments_webhook_receipts_status_check;
ALTER TABLE payments_webhook_receipts ADD CONSTRAINT payments_webhook_receipts_status_check
    CHECK (status IN ('received', 'retrying', 'processed', 'ignored', 'failed', 'dead_letter'));

-- What the retry lane picks up next.
CREATE INDEX idx_payments_webhooks_due ON payments_webhook_receipts (next_attempt_at)
    WHERE status IN ('received', 'retrying');

-- The owner sees a payment whose provider update could not be applied.
ALTER TABLE payments_payment_attempts DROP CONSTRAINT IF EXISTS payments_payment_attempts_attention_check;
ALTER TABLE payments_payment_attempts ADD CONSTRAINT payments_payment_attempts_attention_check
    CHECK (attention IS NULL OR attention IN ('paid_twice', 'not_received', 'refund_due', 'provider_update_failed'));
