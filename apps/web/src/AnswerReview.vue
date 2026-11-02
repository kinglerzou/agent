<template>
  <section
    class="ops-review"
    aria-label="人工审核回答"
  >
    <b>等待人工审核 · 草稿尚未完成</b>
    <p>核对回答与参考知识后，通过、修改后通过或驳回。通过前不会用于后续对话。</p>
    <label>
      <input
        v-model="editing"
        type="checkbox"
        :disabled="submitting"
      >
      修改草稿后通过
    </label>
    <textarea
      v-if="editing"
      v-model="editedAnswer"
      aria-label="修改后的回答"
      maxlength="24000"
      rows="7"
      :disabled="submitting"
    />
    <label>
      审核意见（驳回必填）
      <textarea
        v-model="comment"
        maxlength="2000"
        rows="2"
        :disabled="submitting"
      />
    </label>
    <div class="ops-review-actions">
      <button
        class="ops-primary"
        :disabled="submitting || (editing && !editedAnswer.trim())"
        @click="submit(editing ? 'edit' : 'approve')"
      >
        {{ submitting ? '正在提交…' : editing ? '修改后通过' : '通过审核' }}
      </button>
      <button
        class="ops-delete"
        :disabled="submitting || !comment.trim()"
        @click="submit('reject')"
      >
        驳回
      </button>
    </div>
    <p
      v-if="error"
      class="ops-error"
      role="alert"
    >
      {{ error }}
    </p>
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{ conversationId: string; turnId: string; draft: string }>();
const emit = defineEmits<{ reviewed: [message: Record<string, unknown>] }>();
const editing = ref(false);
const editedAnswer = ref('');

watch(() => props.draft, (draft) => { editedAnswer.value = draft; }, { immediate: true });

const comment = ref('');
const submitting = ref(false);
const error = ref('');

async function submit(action: 'approve' | 'edit' | 'reject') {
  if (submitting.value) return;
  submitting.value = true;
  error.value = '';
  try {
    const response = await fetch(`/api/game/conversations/${props.conversationId}/turns/${props.turnId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, answer: action === 'edit' ? editedAnswer.value : '', comment: comment.value }),
    });

    const result = await response.json() as Record<string, unknown>;
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '审核失败，请重试');
    emit('reviewed', result);
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审核提交失败，请重试';
  } finally {
    submitting.value = false;
  }
}
</script>
