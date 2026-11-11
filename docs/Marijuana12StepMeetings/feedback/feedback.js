"use strict";

const form = document.getElementById("feedback-form");
const message = document.getElementById("message");
const email = document.getElementById("email");
const send = document.getElementById("send-feedback");
const status = document.getElementById("feedback-status");
const success = document.getElementById("feedback-success");
let submitting = false;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submitting) return;

  message.setCustomValidity(message.value.trim() ? "" : "Please enter your feedback.");
  if (!form.reportValidity()) return;

  const fields = Object.fromEntries(new FormData(form));
  fields.message = message.value.trim();
  const replyAddress = email.value.trim();
  if (replyAddress) fields.email = replyAddress;
  else delete fields.email;

  const endpoint = new URL(form.action);
  endpoint.pathname = "/ajax" + endpoint.pathname;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);

  submitting = true;
  send.disabled = true;
  message.readOnly = true;
  email.readOnly = true;
  form.setAttribute("aria-busy", "true");
  status.dataset.state = "sending";
  status.textContent = "Sending your feedback…";

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(fields),
      signal: controller.signal,
    });
    const result = await response.json();
    if (!response.ok || (result.success !== true && result.success !== "true")) {
      throw new Error("Submission was not confirmed.");
    }

    form.reset();
    form.hidden = true;
    success.hidden = false;
    document.getElementById("success-title").focus();
  } catch {
    status.dataset.state = "error";
    status.textContent = "We couldn’t confirm your submission. Your message is still here. You can try again or use Contact by email below.";
  } finally {
    clearTimeout(timeout);
    submitting = false;
    send.disabled = false;
    message.readOnly = false;
    email.readOnly = false;
    form.removeAttribute("aria-busy");
  }
});

message.addEventListener("input", () => message.setCustomValidity(""));
