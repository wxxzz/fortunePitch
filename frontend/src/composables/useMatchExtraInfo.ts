import { computed, reactive, ref } from 'vue'
import { getMatchExtraInfo, saveMatchExtraInfo } from '@/api/match/extraInfo'

/** 单字段录入上限(与后端 schema 对齐) */
export const EXTRA_FIELD_MAX_LENGTH = 5000

/** 补充信息表单字段(空记录基线) */
const EMPTY_FORM = { injuries: '', formations: '', other_notes: '' }

/**
 * 人工录入补充信息(伤停/阵型等)的表单状态与保存动作。
 *
 * 由父组件持有单一实例:顶部对战卡片的阵型摘要与"其他信息" Tab 的
 * 录入表单共享同一份表单数据,切换 Tab 不丢编辑中内容。
 * 返回 reactive 捆绑对象,便于作为单一 prop 传给录入 Tab 组件。
 */
export function useMatchExtraInfo(matchId: string) {
  const form = ref({ ...EMPTY_FORM })
  /** 最近一次已保存的快照,用于未保存更改提示 */
  const saved = ref({ ...EMPTY_FORM })
  const updatedAt = ref<string | null>(null)
  const isLoading = ref(true)
  const isSaving = ref(false)
  const loadError = ref<string | null>(null)
  const saveError = ref<string | null>(null)
  const saveMessage = ref('')

  /** 表单内容与最近一次保存的快照不一致时提示,避免误切 Tab 丢失编辑 */
  const isDirty = computed(
    () =>
      form.value.injuries !== saved.value.injuries ||
      form.value.formations !== saved.value.formations ||
      form.value.other_notes !== saved.value.other_notes,
  )

  /** 顶部对战卡片的阵型摘要:取已录入阵型的首行,未录入时提示录入入口 */
  const heroFormationText = computed(() => {
    const text = form.value.formations.trim()
    if (!text) return '伤停/阵型信息可在"其他信息"页签录入'
    return `阵型:${text.split('\n')[0]}`
  })

  /** 加载已保存的补充信息(未录入时后端返回空记录) */
  async function load(): Promise<void> {
    isLoading.value = true
    loadError.value = null
    try {
      const data = await getMatchExtraInfo(matchId)
      form.value = {
        injuries: data.injuries ?? '',
        formations: data.formations ?? '',
        other_notes: data.other_notes ?? '',
      }
      saved.value = { ...form.value }
      updatedAt.value = data.updated_at
    } catch (err) {
      loadError.value = err instanceof Error ? err.message : '补充信息加载失败'
    } finally {
      isLoading.value = false
    }
  }

  /** 保存补充信息(整体覆盖语义),成功后提示注入生效范围 */
  async function save(): Promise<void> {
    if (isSaving.value) return
    isSaving.value = true
    saveError.value = null
    saveMessage.value = ''
    try {
      const data = await saveMatchExtraInfo(matchId, { ...form.value })
      saved.value = { ...form.value }
      updatedAt.value = data.updated_at
      saveMessage.value = '已保存,后续 AI 综合分析与基本面分析将自动带上本页信息'
      window.setTimeout(() => {
        saveMessage.value = ''
      }, 4000)
    } catch (err) {
      saveError.value = err instanceof Error ? err.message : '补充信息保存失败'
    } finally {
      isSaving.value = false
    }
  }

  return reactive({
    form,
    saved,
    updatedAt,
    isLoading,
    isSaving,
    loadError,
    saveError,
    saveMessage,
    isDirty,
    heroFormationText,
    load,
    save,
  })
}

export type MatchExtraInfoState = ReturnType<typeof useMatchExtraInfo>
