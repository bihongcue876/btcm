<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  creative: boolean
  validator: boolean
}>()
const emit = defineEmits<{
  'update:creative': [value: boolean]
  'update:validator': [value: boolean]
}>()

interface ShapeMeta {
  key: string
  label: string
  desc: string
  c: boolean
  v: boolean
}

const shapes: ShapeMeta[] = [
  { key: 'hybrid', label: '完整循环', desc: '生成 → 验证 → 反思', c: true, v: true },
  { key: 'creative', label: '纯创意', desc: '单次发散候选', c: true, v: false },
  { key: 'validation', label: '纯验证', desc: '单次判定候选', c: false, v: true },
  { key: 'longchain', label: '长链持续思考', desc: 'controller 多轮自省', c: false, v: false },
]

const active = computed<ShapeMeta>(() => {
  if (props.creative && props.validator) return shapes[0]
  if (props.creative) return shapes[1]
  if (props.validator) return shapes[2]
  return shapes[3]
})

function select(s: ShapeMeta) {
  if (s.c !== props.creative) emit('update:creative', s.c)
  if (s.v !== props.validator) emit('update:validator', s.v)
}
</script>

<template>
  <div class="shape-indicator" role="tablist" aria-label="运行形态">
    <button
      v-for="s in shapes"
      :key="s.key"
      type="button"
      role="tab"
      :aria-selected="s.key === active.key"
      class="shape-item"
      :class="[`shape-${s.key}`, { active: s.key === active.key }]"
      @click="select(s)"
    >
      <span class="shape-label">{{ s.label }}</span>
      <span class="shape-desc">{{ s.desc }}</span>
    </button>
  </div>
  <p class="shape-hint">总控恒启用 · 双关为长链持续思考</p>
</template>

<style scoped>
.shape-indicator {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.shape-item {
  appearance: none;
  text-align: left;
  cursor: pointer;
  font: inherit;
  color: inherit;
  border: 1px solid rgba(255, 255, 255, 0.07);
  border-radius: 12px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.02);
  transition: border-color 0.25s, box-shadow 0.25s, background 0.25s, transform 0.25s;
}
.shape-item:hover {
  border-color: rgba(255, 255, 255, 0.18);
}
.shape-item:active {
  transform: translateY(1px);
}
.shape-label {
  display: block;
  font-size: 14px;
  font-weight: 500;
  color: #8b93a7;
  transition: color 0.25s;
}
.shape-desc {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: #5d6474;
  transition: color 0.25s;
}
.shape-hybrid.active {
  border-color: rgba(110, 140, 255, 0.55);
  background: rgba(110, 140, 255, 0.1);
  box-shadow: 0 0 18px rgba(110, 140, 255, 0.18);
}
.shape-hybrid.active .shape-label {
  color: #a8bcff;
}
.shape-hybrid.active .shape-desc {
  color: #7f90c9;
}
.shape-creative.active {
  border-color: rgba(91, 155, 255, 0.5);
  background: rgba(91, 155, 255, 0.09);
  box-shadow: 0 0 18px rgba(91, 155, 255, 0.16);
}
.shape-creative.active .shape-label {
  color: #9cc2ff;
}
.shape-validation.active {
  border-color: rgba(230, 162, 60, 0.5);
  background: rgba(230, 162, 60, 0.08);
  box-shadow: 0 0 18px rgba(230, 162, 60, 0.14);
}
.shape-validation.active .shape-label {
  color: #f0c37a;
}
.shape-longchain.active {
  border-color: rgba(160, 120, 255, 0.6);
  background: rgba(160, 120, 255, 0.1);
  box-shadow: 0 0 20px rgba(160, 120, 255, 0.22);
}
.shape-longchain.active .shape-label {
  color: #c9b1ff;
}
.shape-longchain.active .shape-desc {
  color: #9a87d0;
}
.shape-hint {
  margin: 8px 2px 0;
  font-size: 12px;
  color: #6b7280;
}
@media (max-width: 640px) {
  .shape-indicator {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
