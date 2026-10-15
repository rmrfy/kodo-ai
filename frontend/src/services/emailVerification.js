let initialEmailVerificationToken = ''

export function setInitialEmailVerificationToken(token) {
  initialEmailVerificationToken = token || ''
}

export function takeInitialEmailVerificationToken() {
  const token = initialEmailVerificationToken
  initialEmailVerificationToken = ''
  return token
}
