<template>
    <!-- fxlint fixture: the CEF paints a filtered area solid black -->
    <div class="panel">core-plugin-bad</div>
</template>

<style scoped>
.panel {
    backdrop-filter: blur(8px);               /* expect: K006 */
}
</style>
