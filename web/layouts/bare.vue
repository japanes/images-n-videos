<template>
  <!-- Full-screen tools (clip editor, image viewer) that bring their own chrome. -->
  <div class="h-dvh overflow-hidden">
    <slot />
    <ConfirmDialog />
    <ToastHost />
  </div>
</template>
