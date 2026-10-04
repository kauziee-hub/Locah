import { redirect } from 'next/navigation'
import { getAccessToken } from '@/lib/supabase/access-token'
import { apiTry } from '@/lib/api'
import { GateNotice, PageHeader } from '@/components/ui'
import { saveRecipe } from '../supply-actions'
import { SafeForm } from '@/components/SafeForm'

export const dynamic = 'force-dynamic'

type Line = { component_offering_id: string; component: string; unit: string; quantity_per: number }
type Recipe = { id: string; dish: string; offering_id: string; lines: Line[] }
type Offering = { id: string; title: string; offering_type: string; track_inventory?: boolean; stock_unit?: string }

export default async function RecipesPage({ params }: { params: { businessId: string } }) {
  const token = await getAccessToken()
  if (!token) redirect('/login')
  const b = params.businessId
  const recipes = await apiTry<{ data: Recipe[] }>(`/v1/platform/businesses/${b}/recipes`, token)
  if (!recipes.ok) {
    return <div className="bos-page"><PageHeader title="Recipes" /><GateNotice error={recipes.error} businessId={b} moduleLabel="Recipes & BOM" /></div>
  }
  const products = await apiTry<{ data: Offering[] }>(`/v1/platform/businesses/${b}/products`, token)
  const offerings = products.ok ? products.data.data : []
  const stocked = offerings.filter((o) => o.track_inventory)
  const rows = recipes.data.data
  return (
    <div className="bos-page">
      <PageHeader
        title="Recipes"
        subtitle="What each dish is made of. When the kitchen finishes a ticket, its ingredients come off stock once."
      />
      {rows.length === 0 ? (
        <p className="bos-empty">No recipes yet. Add one below; dishes without a recipe use no stock.</p>
      ) : (
        <table className="bos-table">
          <thead><tr><th>Dish</th><th>Ingredients per dish</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.dish}</td>
                <td>{r.lines.map((l) => `${l.component} ${l.quantity_per} ${l.unit}`).join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <SafeForm action={saveRecipe} className="bos-form">
        <h2>Add or replace a recipe</h2>
        <input type="hidden" name="businessId" value={b} />
        <label>Dish
          <select name="offering_id" required defaultValue="">
            <option value="" disabled>Choose a dish</option>
            {offerings.map((o) => <option key={o.id} value={o.id}>{o.title}</option>)}
          </select>
        </label>
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="bos-form-row">
            <label>Ingredient {i + 1}
              <select name={`component_${i}`} defaultValue="">
                <option value="">—</option>
                {stocked.map((o) => <option key={o.id} value={o.id}>{o.title}{o.stock_unit ? ` (${o.stock_unit})` : ''}</option>)}
              </select>
            </label>
            <label>Per dish<input name={`quantity_${i}`} type="number" min={0} step="0.001" /></label>
          </div>
        ))}
        <button type="submit" className="btn-primary">Save recipe</button>
      </SafeForm>
    </div>
  )
}
