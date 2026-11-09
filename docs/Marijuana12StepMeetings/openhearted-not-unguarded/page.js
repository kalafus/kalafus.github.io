"use strict";

{
  const principles = [...document.querySelectorAll("details.principle")];
  const expandAll = document.querySelector(".expand-all");
  const updateExpandButton = () => {
    if (expandAll) expandAll.textContent = principles.every((principle) => principle.open) ? "Collapse all" : "Expand all";
  };

  if (expandAll) {
    expandAll.hidden = false;
    expandAll.addEventListener("click", () => {
      const open = !principles.every((principle) => principle.open);
      principles.forEach((principle) => { principle.open = open; });
      updateExpandButton();
    });
  }
  principles.forEach((principle) => principle.addEventListener("toggle", updateExpandButton));

  const openLinkedPrinciple = () => {
    const principle = principles.find((item) => `#${item.id}` === window.location.hash);
    if (principle) {
      principle.open = true;
      principle.querySelector("summary").focus({ preventScroll: true });
      principle.scrollIntoView();
    }
  };
  openLinkedPrinciple();
  window.addEventListener("hashchange", openLinkedPrinciple);

  // Printing includes every explanation, then restores the reader's open sections.
  let beforePrint = null;
  window.addEventListener("beforeprint", () => {
    if (beforePrint !== null) return;
    beforePrint = principles.map((principle) => principle.open);
    principles.forEach((principle) => { principle.open = true; });
  });
  window.addEventListener("afterprint", () => {
    if (beforePrint === null) return;
    principles.forEach((principle, index) => { principle.open = beforePrint[index]; });
    beforePrint = null;
    updateExpandButton();
  });

  const appearance = document.getElementById("appearance");
  const applyAppearance = () => {
    if (appearance.value === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = appearance.value;
  };
  // Keep the reader's choice while moving between the two reading views.
  // Storage can be unavailable for local files or restricted browser sessions.
  try {
    const saved = sessionStorage.getItem("openhearted-appearance");
    if (saved === "light" || saved === "dark") appearance.value = saved;
  } catch {}
  applyAppearance();
  appearance.parentElement.hidden = false;
  appearance.addEventListener("change", () => {
    applyAppearance();
    try {
      if (appearance.value === "system") sessionStorage.removeItem("openhearted-appearance");
      else sessionStorage.setItem("openhearted-appearance", appearance.value);
    } catch {}
  });
}
