'use server'

import { revalidatePath } from 'next/cache'
import { sendJson, type ActionResult } from '@/lib/server-send'

/** One write for Buying, Expenses, Donations and Recipes; answers with the API's reason when refused. */
async function post(businessId: string, path: string, body: unknown, refresh: string, method = 'POST'): Promise<ActionResult> {
  const r = await sendJson(`/v1/platform/businesses/${businessId}${path}`, method, body)
  if (r.ok) revalidatePath(`/b/${businessId}/${refresh}`)
  return r
}

export async function prepareRequirement(form: FormData) {
  const businessId = String(form.get('businessId'))
  return post(businessId, '/buying/prepare', {
    supplier_id: String(form.get('supplier_id')),
    offering_id: String(form.get('offering_id')),
    demand: Number(form.get('demand') || 0),
    location_id: String(form.get('location_id') || '') || null,
    pack_size: Number(form.get('pack_size') || 1),
    moq: Number(form.get('moq') || 1),
  }, 'buying')
}

export async function approveRequirement(form: FormData) {
  const businessId = String(form.get('businessId'))
  const requisitionId = String(form.get('requisitionId'))
  return post(businessId, `/buying/requisitions/${requisitionId}/approve`, {}, 'buying')
}

export async function receiveGoods(form: FormData) {
  const businessId = String(form.get('businessId'))
  const purchaseOrderId = String(form.get('purchaseOrderId'))
  return post(businessId, `/buying/purchase-orders/${purchaseOrderId}/receive`, {
    location_id: String(form.get('location_id')),
    received_quantity: Number(form.get('received_quantity') || 0),
    damaged_quantity: Number(form.get('damaged_quantity') || 0),
    idempotency_key: `ui-${purchaseOrderId}-${Date.now()}`,
  }, 'buying')
}

export async function addSupplier(form: FormData) {
  const businessId = String(form.get('businessId'))
  return post(businessId, '/suppliers', {
    name: String(form.get('name') || '').trim(),
    contact_name: String(form.get('contact_name') || '') || null,
    phone: String(form.get('phone') || '') || null,
    connection: 'off_network',
    credit_days: Number(form.get('credit_days') || 0),
  }, 'buying')
}

export async function addExpense(form: FormData) {
  const businessId = String(form.get('businessId'))
  const rupees = Number(form.get('rupees') || 0)
  return post(businessId, '/expenses', {
    category: String(form.get('category') || '').trim(),
    amount_paise: Math.round(rupees * 100),
    method: String(form.get('method') || 'cash'),
    payee: String(form.get('payee') || '') || null,
    petty_cash: form.get('petty_cash') === 'on',
  }, 'expenses')
}

export async function addCause(form: FormData) {
  const businessId = String(form.get('businessId'))
  return post(businessId, '/donations/causes', { name: String(form.get('name') || '').trim() }, 'donations')
}

export async function addGift(form: FormData) {
  const businessId = String(form.get('businessId'))
  const rupees = Number(form.get('rupees') || 0)
  return post(businessId, '/donations/gifts', {
    cause_id: String(form.get('cause_id')),
    donor_name: String(form.get('donor_name') || '').trim(),
    amount_paise: Math.round(rupees * 100),
  }, 'donations')
}

export async function saveRecipe(form: FormData) {
  const businessId = String(form.get('businessId'))
  const lines = [0, 1, 2, 3, 4]
    .map((i) => ({
      component_offering_id: String(form.get(`component_${i}`) || ''),
      quantity_per: Number(form.get(`quantity_${i}`) || 0),
    }))
    .filter((line) => line.component_offering_id && line.quantity_per > 0)
  return post(businessId, '/recipes', { offering_id: String(form.get('offering_id')), lines }, 'recipes', 'PUT')
}
