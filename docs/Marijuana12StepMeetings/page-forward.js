"use strict";

// The visible link owns the destination; retain bookmarked sections and queries.
{
  const link = document.getElementById("page-destination");
  const destination = new URL(link.href);
  destination.search = window.location.search;
  destination.hash = window.location.hash;
  link.href = destination.href;
  window.location.replace(destination.href);
}
