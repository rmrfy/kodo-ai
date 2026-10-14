<script setup>
import SettingsPanel from '../components/settings/SettingsPanel.vue'

defineProps({ settingsProps: { type: Object, default: () => ({}) } })

const emit = defineEmits([
  'connect', 'refresh-installations', 'connect-installation', 'invite-member', 'switch-organization',
  'create-organization', 'rename-organization', 'link-email-password', 'change-member-role',
  'remove-member', 'revoke-invite', 'mode', 'toggle-repo', 'logout',
  'save-organization-context', 'save-repository-context',
])

function forwardEvent(name, ...args) {
  emit(name, ...args)
}
</script>

<template>
  <SettingsPanel
    v-bind="settingsProps"
    @connect="emit('connect')"
    @refresh-installations="emit('refresh-installations')"
    @connect-installation="emit('connect-installation', $event)"
    @invite-member="emit('invite-member', $event)"
    @switch-organization="emit('switch-organization', $event)"
    @create-organization="emit('create-organization', $event)"
    @rename-organization="emit('rename-organization', $event)"
    @link-email-password="emit('link-email-password', $event)"
    @change-member-role="emit('change-member-role', $event)"
    @remove-member="emit('remove-member', $event)"
    @revoke-invite="emit('revoke-invite', $event)"
    @mode="(...args) => forwardEvent('mode', ...args)"
    @toggle-repo="emit('toggle-repo', $event)"
    @logout="emit('logout')"
    @save-organization-context="(...args) => forwardEvent('save-organization-context', ...args)"
    @save-repository-context="(...args) => forwardEvent('save-repository-context', ...args)"
  />
</template>
