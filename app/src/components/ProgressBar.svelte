<script lang="ts">
  let { message = "" }: { message?: string } = $props();
</script>

<div class="progress">
  <div class="track">
    <div class="fill"></div>
  </div>
  {#if message}
    {#key message}
      <p class="msg">{message}</p>
    {/key}
  {/if}
</div>

<style>
  .progress {
    width: 100%;
    max-width: 280px;
  }

  .track {
    height: 2px;
    background: rgba(0, 0, 0, 0.05);
    border-radius: 2px;
    overflow: hidden;
  }

  .fill {
    height: 100%;
    width: 35%;
    background: #8b7e74;
    border-radius: 2px;
    animation: slide 1.8s cubic-bezier(0.4, 0, 0.2, 1) infinite;
  }

  @keyframes slide {
    0% { transform: translateX(-120%); }
    100% { transform: translateX(400%); }
  }

  .msg {
    margin-top: 12px;
    font-size: 11px;
    color: #807870;
    text-align: center;
    letter-spacing: 0.02em;
    user-select: none;
    animation: msgIn 0.4s ease;
  }

  @keyframes msgIn {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
  }

  @media (prefers-color-scheme: dark) {
    .track {
      background: rgba(255, 255, 255, 0.06);
    }

    .fill {
      background: #a09080;
    }

    .msg {
      color: #8a8078;
    }
  }
</style>
