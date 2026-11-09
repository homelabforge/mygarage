import { QueryClient } from '@tanstack/react-query'

/**
 * The app's one query cache. App.tsx provides it above AuthProvider, so
 * AuthContext reads public settings through the same cache as every page.
 * Code inside the tree takes it from `useQueryClient()`, never from here, so a
 * test's own client is the one that gets used.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
})
