/**
 * User type definitions for the multi-user system.
 */

export type AuthMethod = 'local' | 'oidc'

export interface User {
  id: number
  username: string
  email: string
  full_name: string | null
  is_active: boolean
  is_admin: boolean
  auth_method: AuthMethod
  oidc_subject: string | null
  oidc_provider: string | null
  created_at: string
  updated_at: string
  last_login: string | null
  // Family fields
  relationship: string | null
  relationship_custom: string | null
  show_on_family_dashboard: boolean
  family_dashboard_order: number
}
