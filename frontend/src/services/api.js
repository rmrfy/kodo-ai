export function createApiClient({ baseUrl = '', onUnauthorized = () => {} } = {}) {
  return async function api(path, options = {}) {
    const response = await fetch(`${baseUrl}/api${path}`, {
      credentials: 'include',
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    })

    if (response.status === 401) {
      onUnauthorized()
      throw new Error('Sign in to continue.')
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || 'Something went wrong')
    }
    return response.json()
  }
}
