<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Check, ChevronDown } from '@lucide/vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  ariaLabel: { type: String, required: true },
  placeholder: { type: String, default: 'Select an option' },
  disabled: { type: Boolean, default: false },
  align: { type: String, default: 'start' },
})
const emit = defineEmits(['update:modelValue'])

const id = useId()
const root = ref(null)
const trigger = ref(null)
const popover = ref(null)
const open = ref(false)
const activeIndex = ref(-1)
const opensAbove = ref(false)
const popoverStyle = ref({})
const optionElements = ref([])
const selectedIndex = computed(() => props.options.findIndex(option => option.value === props.modelValue))
const selectedOption = computed(() => props.options[selectedIndex.value] || null)

function focusOption(index) {
  const bounded = Math.max(0, Math.min(index, props.options.length - 1))
  activeIndex.value = bounded
  nextTick(() => optionElements.value[bounded]?.focus())
}

function showMenu(index = selectedIndex.value >= 0 ? selectedIndex.value : 0) {
  if (props.disabled || !props.options.length) return
  open.value = true
  focusOption(index)
}

function positionMenu() {
  if (!open.value || !trigger.value || !popover.value) return
  const anchor = trigger.value.getBoundingClientRect()
  const menu = popover.value.getBoundingClientRect()
  const gap = 6
  const gutter = 8
  const roomBelow = window.innerHeight - anchor.bottom - gutter
  const roomAbove = anchor.top - gutter
  opensAbove.value = roomBelow < menu.height + gap && roomAbove > roomBelow
  const width = Math.max(menu.width, Math.min(anchor.width, window.innerWidth - gutter * 2))
  const top = opensAbove.value
    ? Math.max(gutter, anchor.top - menu.height - gap)
    : Math.min(window.innerHeight - menu.height - gutter, anchor.bottom + gap)
  const left = props.align === 'end' ? anchor.right - width : anchor.left
  const clampedLeft = Math.max(gutter, Math.min(left, window.innerWidth - width - gutter))
  popoverStyle.value = {
    left: `${clampedLeft}px`,
    top: `${top}px`,
    width: `${width}px`,
  }
}

function handleViewportChange() {
  positionMenu()
}

function closeMenu(returnFocus = false) {
  open.value = false
  if (returnFocus) nextTick(() => trigger.value?.focus())
}

function toggleMenu() {
  if (open.value) closeMenu()
  else showMenu()
}

function choose(option) {
  if (option.disabled) return
  emit('update:modelValue', option.value)
  closeMenu(true)
}

function handleTriggerKeydown(event) {
  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (!open.value) showMenu()
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (!open.value) showMenu(props.options.length - 1)
  }
}

function handleOptionKeydown(event, index) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    focusOption((index + 1) % props.options.length)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    focusOption((index - 1 + props.options.length) % props.options.length)
  } else if (event.key === 'Home') {
    event.preventDefault()
    focusOption(0)
  } else if (event.key === 'End') {
    event.preventDefault()
    focusOption(props.options.length - 1)
  } else if (event.key === 'Escape') {
    event.preventDefault()
    closeMenu(true)
  } else if (event.key === 'Tab') {
    event.preventDefault()
    const direction = event.shiftKey ? -1 : 1
    const focusable = [...document.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
      .filter(element => !popover.value?.contains(element) && element.getClientRects().length)
    const triggerIndex = focusable.indexOf(trigger.value)
    closeMenu()
    nextTick(() => focusable[triggerIndex + direction]?.focus())
  }
}

function handleOutsidePointer(event) {
  if (open.value && !root.value?.contains(event.target) && !popover.value?.contains(event.target)) closeMenu()
}

watch(open, isOpen => {
  if (isOpen) {
    positionMenu()
    window.addEventListener('resize', handleViewportChange)
    window.addEventListener('scroll', handleViewportChange, true)
  } else {
    window.removeEventListener('resize', handleViewportChange)
    window.removeEventListener('scroll', handleViewportChange, true)
  }
}, { flush: 'post' })

onMounted(() => document.addEventListener('pointerdown', handleOutsidePointer))
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleOutsidePointer)
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
})
</script>

<template>
  <div ref="root" class="select-menu" :class="[{ 'is-open': open, 'is-disabled': disabled }, `align-${align}`]">
    <button
      :id="`${id}-trigger`"
      ref="trigger"
      class="select-menu-trigger"
      type="button"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-haspopup="'listbox'"
      :aria-expanded="open"
      :aria-controls="`${id}-options`"
      @click="toggleMenu"
      @keydown="handleTriggerKeydown"
    >
      <span class="select-menu-value">{{ selectedOption?.label || placeholder }}</span>
      <ChevronDown class="select-menu-chevron" :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>

  </div>
  <Teleport to="body">
    <Transition name="select-popover">
      <div
        v-if="open"
        :id="`${id}-options`"
        ref="popover"
        class="select-menu-popover"
        :class="{ 'opens-above': opensAbove }"
        :style="popoverStyle"
        role="listbox"
        :aria-label="ariaLabel"
      >
        <button
          v-for="(option, index) in options"
          :key="option.value"
          :ref="element => { if (element) optionElements[index] = element }"
          class="select-menu-option"
          :class="{ selected: option.value === modelValue, active: activeIndex === index }"
          type="button"
          role="option"
          :tabindex="activeIndex === index ? 0 : -1"
          :aria-selected="option.value === modelValue"
          :disabled="option.disabled"
          @click="choose(option)"
          @mouseenter="activeIndex = index"
          @keydown="handleOptionKeydown($event, index)"
        >
          <span class="select-menu-option-copy">
            <span class="select-menu-option-label">{{ option.label }}</span>
            <small v-if="option.description">{{ option.description }}</small>
          </span>
          <Check v-if="option.value === modelValue" class="select-menu-check" :size="15" :stroke-width="2" aria-hidden="true" />
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.select-menu { position: relative; display: inline-flex; min-width: 0; color: #39483f; }
.select-menu-trigger { display: flex; align-items: center; justify-content: space-between; width: 100%; min-width: 0; min-height: 38px; gap: 12px; padding: 0 10px 0 11px; border: 1px solid #dfe6df; border-radius: 8px; background: #fff; color: #46564b; font-size: 12px; text-align: left; cursor: pointer; transition: background .14s ease, border-color .14s ease, box-shadow .14s ease; }
.select-menu-trigger:hover, .is-open .select-menu-trigger { border-color: #c8d7cb; background: #fcfdfb; }
.select-menu-trigger:focus-visible { outline: 2px solid #6e9c7c; outline-offset: 2px; }
.select-menu-value { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-menu-chevron { flex: none; color: #7f8c82; transition: transform .16s ease; }
.is-open .select-menu-chevron { transform: rotate(180deg); }
.select-menu-trigger:disabled { background: #f7f8f6; color: #9aa39c; cursor: not-allowed; }
.select-menu-popover { position: fixed; z-index: 1000; width: max-content; max-width: min(320px, calc(100vw - 16px)); max-height: min(280px, calc(100vh - 16px)); overflow-y: auto; padding: 5px; border: 1px solid #e0e7e0; border-radius: 10px; background: #fff; box-shadow: 0 12px 32px #25372d1c, 0 2px 6px #25372d0b; }
.select-menu-option { display: flex; align-items: center; justify-content: space-between; width: 100%; gap: 12px; padding: 8px 9px; border: 0; border-radius: 6px; background: transparent; color: #56645a; font-size: 12px; text-align: left; cursor: pointer; }
.select-menu-option:hover, .select-menu-option.active { background: #f4f7f3; color: #365841; }
.select-menu-option.selected { color: #315f4a; font-weight: 600; }
.select-menu-option:disabled { opacity: .5; cursor: not-allowed; }
.select-menu-option-copy { display: grid; gap: 3px; min-width: 0; }
.select-menu-option-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.select-menu-option small { color: #89948c; font-size: 10px; font-weight: 400; }
.select-menu-check { flex: none; color: #54765c; }
.select-popover-enter-active, .select-popover-leave-active { transition: opacity .12s ease, transform .12s ease; }
.select-popover-enter-from, .select-popover-leave-to { opacity: 0; transform: translateY(3px); }
.select-menu-popover.opens-above.select-popover-enter-from, .select-menu-popover.opens-above.select-popover-leave-to { transform: translateY(-3px); }
</style>
