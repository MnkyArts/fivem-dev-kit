<!-- fxlint fixture -- a page built from the kit only: no import, no CSS of its own, no
     backdrop filter (K006), no createApp and no NUI callback (K017). -->
<script setup lang="ts">
import { usePage } from '@core/ui'
import type { GoodProps } from './index.ts'

const { props, close } = usePage<GoodProps>()
</script>

<template>
    <CoreScreen>
        <CorePanel blur title="core-plugin-good">
            <p class="text-fg-dim">Cash: {{ props.cash }}</p>
            <CoreButton @click="close()">Close</CoreButton>
        </CorePanel>
    </CoreScreen>
</template>
