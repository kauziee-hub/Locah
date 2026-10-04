-- A refund request can carry an idempotency key. The same key on the same
-- payment returns the refund already made (a double-click, a retried request)
-- instead of refunding twice; reusing a key for a different amount is refused.

ALTER TABLE payments_refunds ADD COLUMN idempotency_key TEXT;

CREATE UNIQUE INDEX uq_payments_refunds_idempotency
    ON payments_refunds (business_id, payment_attempt_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
