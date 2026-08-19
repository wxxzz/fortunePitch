<script setup lang="ts">
/**
 * 基础档案模块视图:联赛 / 球队 / 球员档案的查看与管理。
 */
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useBaseStore } from '@/stores/base'

const baseStore = useBaseStore()
const { leagues, teams, players, isLoading, error } = storeToRefs(baseStore)

onMounted(() => {
  void baseStore.fetchAll()
})
</script>

<template>
  <section class="base-data">
    <h2 class="base-data__title">基础档案 · 联赛 / 球队 / 球员</h2>

    <p v-if="error" class="base-data__error" role="alert">{{ error }}</p>
    <p v-if="isLoading" class="base-data__hint">加载中…</p>

    <h3 class="base-data__section-title">联赛</h3>
    <table class="base-data__table">
      <thead>
        <tr>
          <th>ID</th><th>名称</th><th>国家</th><th>级别</th><th>赛季</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="league in leagues" :key="league.league_id">
          <td>{{ league.league_id }}</td>
          <td>{{ league.league_name }}</td>
          <td>{{ league.country }}</td>
          <td>{{ league.tier }}</td>
          <td>{{ league.season }}</td>
          <td>
            <button
              class="base-data__btn base-data__btn--danger"
              type="button"
              @click="baseStore.removeLeague(league.league_id)"
            >
              删除
            </button>
          </td>
        </tr>
        <tr v-if="leagues.length === 0">
          <td colspan="6" class="base-data__empty">暂无数据</td>
        </tr>
      </tbody>
    </table>

    <h3 class="base-data__section-title">球队</h3>
    <table class="base-data__table">
      <thead>
        <tr>
          <th>ID</th><th>名称</th><th>联赛 ID</th><th>主场</th><th>主教练</th><th>阵型</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="team in teams" :key="team.team_id">
          <td>{{ team.team_id }}</td>
          <td>{{ team.team_name }}</td>
          <td>{{ team.league_id }}</td>
          <td>{{ team.stadium ?? '-' }}</td>
          <td>{{ team.manager ?? '-' }}</td>
          <td>{{ team.formation ?? '-' }}</td>
        </tr>
        <tr v-if="teams.length === 0">
          <td colspan="6" class="base-data__empty">暂无数据</td>
        </tr>
      </tbody>
    </table>

    <h3 class="base-data__section-title">球员</h3>
    <table class="base-data__table">
      <thead>
        <tr>
          <th>ID</th><th>姓名</th><th>球队 ID</th><th>位置</th><th>出生日期</th><th>身价(€)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="player in players" :key="player.player_id">
          <td>{{ player.player_id }}</td>
          <td>{{ player.player_name }}</td>
          <td>{{ player.team_id }}</td>
          <td>{{ player.position ?? '-' }}</td>
          <td>{{ player.birth_date ?? '-' }}</td>
          <td>{{ player.market_value?.toLocaleString() ?? '-' }}</td>
        </tr>
        <tr v-if="players.length === 0">
          <td colspan="6" class="base-data__empty">暂无数据</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/variables' as vars;

.base-data {
  max-width: 1080px;
  margin: 0 auto;

  &__title {
    margin: 0 0 vars.$spacing-lg;
  }

  &__section-title {
    margin: vars.$spacing-lg 0 vars.$spacing-sm;
  }

  &__error {
    color: vars.$color-danger;
  }

  &__hint {
    color: vars.$color-text-secondary;
  }

  &__table {
    width: 100%;
    border-collapse: collapse;
    background: vars.$color-surface;
    border: 1px solid vars.$color-border;
    border-radius: vars.$border-radius;
    margin-bottom: vars.$spacing-md;

    th,
    td {
      padding: vars.$spacing-sm vars.$spacing-md;
      border-bottom: 1px solid vars.$color-border;
      text-align: left;
      font-size: vars.$font-size-md;
    }

    th {
      background: vars.$color-surface-hover;
    }
  }

  &__btn--danger {
    padding: vars.$spacing-xs vars.$spacing-sm;
    border: 1px solid vars.$color-danger;
    border-radius: vars.$border-radius;
    background: transparent;
    color: vars.$color-danger;
    cursor: pointer;
  }

  &__empty {
    color: vars.$color-text-secondary;
    text-align: center;
  }
}
</style>
