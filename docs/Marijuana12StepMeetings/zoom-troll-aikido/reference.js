"use strict";

{
  const headline = document.querySelector(".headline-note");
  const trigger = document.getElementById("concept-five-ref");
  const tooltip = document.getElementById("concept-five-tooltip");
  const note = document.getElementById("concept-five-text");

  // The printed footnote owns the wording; the tooltip is a display copy.
  tooltip.firstElementChild.textContent = note.textContent;
  const showNote = (visible) => {
    tooltip.hidden = !visible;
    trigger.setAttribute("aria-expanded", String(visible));
  };

  headline.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "mouse") showNote(true);
  });
  headline.addEventListener("pointerleave", (event) => {
    if (event.pointerType === "mouse" && !headline.contains(document.activeElement)) showNote(false);
  });
  trigger.addEventListener("focus", () => showNote(true));
  trigger.addEventListener("click", () => showNote(true));
  headline.addEventListener("focusout", (event) => {
    if (!headline.contains(event.relatedTarget) && !headline.matches(":hover")) showNote(false);
  });
  document.addEventListener("pointerdown", (event) => {
    if (!headline.contains(event.target)) showNote(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !tooltip.hidden) {
      showNote(false);
      event.preventDefault();
    }
  });
}

{
  const quote = document.querySelector(".audio-quote");
  const audio = document.getElementById("obisonye-audio");
  const status = document.getElementById("audio-status");
  const showAudioError = () => {
    status.textContent = "Audio couldn’t start. Try the player’s Play button.";
    status.hidden = false;
  };

  quote.addEventListener("click", async (event) => {
    event.preventDefault();
    audio.focus({ preventScroll: true });
    status.hidden = true;
    try {
      await audio.play();
    } catch (error) {
      // Pausing or replacing a pending play request is an expected cancellation.
      if (error.name !== "AbortError" && audio.paused) showAudioError();
    }
  });
  audio.addEventListener("playing", () => { status.hidden = true; });
  audio.addEventListener("error", showAudioError);
}
