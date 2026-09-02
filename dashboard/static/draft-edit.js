/* Targeted revision, and direct editing, of a working draft.
 *
 * The draft is raw Markdown in a <pre>, so a text selection inside it maps
 * 1:1 to character offsets in the stored `current` text — no DOM-range to
 * source mapping. One span edit is in flight at a time: pick a span, give
 * an instruction, see a diff, then accept / retry / reject before the next.
 *
 * The <pre> is also `contenteditable`: typing changes it directly, no
 * separate edit mode. Enter and paste are intercepted so the doc stays
 * plain text (a browser's native contenteditable handling of Enter reaches
 * for a <div>/<br>, which would silently eat the newline from
 * `textContent` and desync the offsets the span-selection code relies on).
 * A change autosaves on blur, and is flushed first if the user hits
 * Download or Undo before that fires, so both act on what's on screen.
 */
(function () {
  "use strict";

  var root = document.querySelector(".draft");
  if (!root) return;

  var draftId = root.dataset.draftId;
  var doc = document.getElementById("draft-doc");
  var reviseBtn = document.getElementById("draft-revise-btn");
  var work = document.getElementById("draft-work");
  var workTitle = document.getElementById("draft-work-title");
  var selectionBox = document.getElementById("draft-selection");
  var ask = document.getElementById("draft-ask");
  var instruction = document.getElementById("draft-instruction");
  var proposeBtn = document.getElementById("draft-propose");
  var cancelBtn = document.getElementById("draft-cancel");
  var closeBtn = document.getElementById("draft-close");
  var proposal = document.getElementById("draft-proposal");
  var diffEl = document.getElementById("draft-diff");
  var noteEl = document.getElementById("draft-note");
  var acceptBtn = document.getElementById("draft-accept");
  var retryBtn = document.getElementById("draft-retry");
  var rejectBtn = document.getElementById("draft-reject");
  var runmeta = document.getElementById("draft-runmeta");
  var costEl = document.getElementById("draft-cost");
  var tokensEl = document.getElementById("draft-tokens");
  var errorEl = document.getElementById("draft-error");
  var busyEl = document.getElementById("draft-busy");
  var undoBtn = document.getElementById("draft-undo");
  var historyWrap = document.getElementById("draft-history-wrap");
  var downloadLink = document.querySelector('.draft__toolbar a[href$="/download"]');
  var docErrorEl = document.getElementById("draft-doc-error");

  var pending = null; // {start, len, selection} while a span is being worked
  var lastProposal = null; // {revised, note, cost}
  var revisionCount = parseInt(root.dataset.revisionCount || "0", 10) || 0;
  var docDirty = false; // the <pre> has been typed in since the last save

  // --- selecting a span ---------------------------------------------------

  // Character offset from the start of the doc text to a (node, offset)
  // boundary. Works whether the boundary node is the <pre>'s text node or
  // the <pre> element itself.
  function offsetWithin(node, nodeOffset) {
    var r = document.createRange();
    r.setStart(doc, 0);
    r.setEnd(node, nodeOffset);
    return r.toString().length;
  }

  // The selection's start/end as offsets into the doc text, clamped to the
  // doc if a drag ran past its edge. null if the selection doesn't touch
  // the doc at all.
  function selectionOffsets() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
    var range = sel.getRangeAt(0);
    var len = doc.textContent.length;
    var startIn = doc.contains(range.startContainer);
    var endIn = doc.contains(range.endContainer);
    if (!startIn && !endIn) return null; // selection is entirely elsewhere
    var start = startIn ? offsetWithin(range.startContainer, range.startOffset) : 0;
    var end = endIn ? offsetWithin(range.endContainer, range.endOffset) : len;
    if (start > end) {
      var t = start;
      start = end;
      end = t;
    }
    return { start: start, end: end, range: range };
  }

  function positionReviseBtn(range, evt) {
    // The button is position:fixed, so these are viewport coordinates —
    // no scroll math, and it doesn't matter what the ancestors are.
    var rect = range.getBoundingClientRect();
    if ((!rect || (rect.width === 0 && rect.height === 0)) && range.getClientRects) {
      var rects = range.getClientRects();
      if (rects.length) rect = rects[rects.length - 1];
    }
    var top, left;
    if (rect && (rect.width || rect.height)) {
      top = rect.bottom + 6;
      left = rect.left;
    } else if (evt) {
      top = evt.clientY + 12;
      left = evt.clientX;
    } else {
      return false;
    }
    // keep it inside the viewport
    left = Math.max(8, Math.min(left, window.innerWidth - 96));
    top = Math.max(8, Math.min(top, window.innerHeight - 44));
    reviseBtn.style.top = top + "px";
    reviseBtn.style.left = left + "px";
    return true;
  }

  function onSelectionSettled(evt) {
    if (pending || !work.hidden) return; // one span edit at a time
    var off = selectionOffsets();
    if (!off || off.end <= off.start || !doc.textContent.slice(off.start, off.end).trim()) {
      hide(reviseBtn);
      return;
    }
    pendingCandidate = { start: off.start, len: off.end - off.start };
    if (positionReviseBtn(off.range, evt)) show(reviseBtn);
  }

  var pendingCandidate = null;

  reviseBtn.addEventListener("click", function () {
    if (!pendingCandidate) return;
    var start = pendingCandidate.start;
    var len = pendingCandidate.len;
    pending = {
      start: start,
      len: len,
      selection: doc.textContent.slice(start, start + len),
    };
    hide(reviseBtn);
    openWork();
  });

  function openWork() {
    hide(reviseBtn);
    selectionBox.textContent = pending.selection;
    workTitle.textContent = "Revise this span";
    instruction.value = "";
    clearError();
    show(ask);
    hide(proposal);
    hide(busyEl);
    show(work);
    highlightPending();
    instruction.focus();
  }

  function highlightPending() {
    // Outline the doc and stop direct typing while a span proposal is
    // open — its offsets are only valid against the text as it was when
    // the span was picked.
    doc.classList.add("draft__doc--locked");
    doc.contentEditable = "false";
  }

  function closeWork() {
    pending = null;
    pendingCandidate = null;
    lastProposal = null;
    hide(work);
    hide(reviseBtn);
    doc.classList.remove("draft__doc--locked");
    doc.contentEditable = "true";
    window.getSelection().removeAllRanges();
  }

  cancelBtn.addEventListener("click", closeWork);
  rejectBtn.addEventListener("click", closeWork);
  if (closeBtn) closeBtn.addEventListener("click", closeWork);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !work.hidden) closeWork();
  });

  // --- proposing a revision -------------------------------------------

  function form(obj) {
    var body = new URLSearchParams();
    Object.keys(obj).forEach(function (k) {
      body.set(k, obj[k]);
    });
    return body;
  }

  function setBusy(on) {
    proposeBtn.disabled = on;
    acceptBtn.disabled = on;
    retryBtn.disabled = on;
    if (on) show(busyEl);
    else hide(busyEl);
  }

  function clearError() {
    errorEl.textContent = "";
    hide(errorEl);
  }

  function showError(msg) {
    errorEl.textContent = msg;
    show(errorEl);
  }

  function propose() {
    if (!pending) return;
    var text = instruction.value.trim();
    if (!text) {
      showError("An instruction is required.");
      return;
    }
    clearError();
    setBusy(true);
    fetch("/drafts/" + draftId + "/revise", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form({
        selection: pending.selection,
        span_start: pending.start,
        span_len: pending.len,
        instruction: text,
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, status: r.status, data: data };
        });
      })
      .then(function (res) {
        setBusy(false);
        if (!res.ok) {
          showError(res.data.error || "The revision failed. Try again.");
          return;
        }
        lastProposal = res.data;
        renderProposal(res.data);
      })
      .catch(function () {
        setBusy(false);
        showError("Could not reach the server. Try again.");
      });
  }

  proposeBtn.addEventListener("click", propose);
  retryBtn.addEventListener("click", propose);

  function renderProposal(data) {
    diffEl.innerHTML = wordDiff(pending.selection, data.revised);
    noteEl.textContent = data.note || "";
    var c = data.cost || {};
    if (typeof c.usd === "number") {
      costEl.textContent = "$" + c.usd.toFixed(4);
      tokensEl.textContent =
        thousands(c.input_tokens) + " in · " + thousands(c.output_tokens) + " out";
      show(runmeta);
    } else {
      hide(runmeta);
    }
    hide(ask);
    show(proposal);
  }

  // --- accepting ------------------------------------------------------

  acceptBtn.addEventListener("click", function () {
    if (!pending || !lastProposal) return;
    setBusy(true);
    clearError();
    // Prefer the offsets /revise resolved server-side (a <pre> can shift
    // them); fall back to what we captured on selection.
    var start = typeof lastProposal.span_start === "number" ? lastProposal.span_start : pending.start;
    var len = typeof lastProposal.span_len === "number" ? lastProposal.span_len : pending.len;
    fetch("/drafts/" + draftId + "/accept", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form({
        selection: pending.selection,
        span_start: start,
        span_len: len,
        instruction: instruction.value.trim(),
        revised: lastProposal.revised,
        note: lastProposal.note || "",
        cost: JSON.stringify(lastProposal.cost || {}),
      }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, status: r.status, data: data };
        });
      })
      .then(function (res) {
        setBusy(false);
        if (!res.ok) {
          showError(res.data.error || "Could not apply the revision.");
          return;
        }
        var accepted = {
          instruction: instruction.value.trim(),
          note: lastProposal.note || "",
        };
        doc.textContent = res.data.current;
        undoBtn.disabled = !res.data.can_undo;
        revisionCount = res.data.revision_count;
        addHistory(accepted);
        closeWork();
      })
      .catch(function () {
        setBusy(false);
        showError("Could not reach the server. Try again.");
      });
  });

  // --- undo ---------------------------------------------------------

  if (undoBtn) {
    undoBtn.addEventListener("click", function () {
      if (undoBtn.disabled) return;
      undoBtn.disabled = true;
      // A not-yet-saved manual edit is the most recent change from the
      // user's point of view — save it first so Undo reverts *that*,
      // same as undoing a just-accepted span revision.
      saveDoc()
        .then(function () {
          return fetch("/drafts/" + draftId + "/undo", { method: "POST" });
        })
        .then(function (r) {
          if (!r.ok) throw new Error();
          return r.json();
        })
        .then(function () {
          window.location.reload();
        })
        .catch(function () {
          undoBtn.disabled = false;
        });
    });
  }

  // --- direct editing -------------------------------------------------
  // The <pre> is contenteditable (see the file banner for why Enter and
  // paste are intercepted). A change is saved as one revision on blur, or
  // first if the user acts on it via Download or Undo before that fires.

  function clearDocError() {
    docErrorEl.textContent = "";
    hide(docErrorEl);
  }

  function showDocError(msg) {
    docErrorEl.textContent = msg;
    show(docErrorEl);
  }

  // Replace the current selection (or just the caret) with plain text,
  // via a Range rather than execCommand — keeps the <pre> as text nodes
  // only, which is what the span-selection offset math assumes.
  function insertPlainText(text) {
    var sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    var range = sel.getRangeAt(0);
    range.deleteContents();
    var node = document.createTextNode(text);
    range.insertNode(node);
    range.setStartAfter(node);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
    docDirty = true;
  }

  doc.addEventListener("input", function () {
    docDirty = true;
  });

  doc.addEventListener("keydown", function (e) {
    if (doc.contentEditable !== "true") return;
    if (e.key === "Enter") {
      // Left to the browser, Enter in a contenteditable inserts a <div> or
      // <br> — an element, not a "\n" character — which textContent drops
      // or splits without a separator. Insert the character ourselves.
      e.preventDefault();
      insertPlainText("\n");
    }
  });

  doc.addEventListener("paste", function (e) {
    if (doc.contentEditable !== "true") return;
    e.preventDefault();
    var clip = e.clipboardData || window.clipboardData;
    insertPlainText(clip ? clip.getData("text/plain") : "");
  });

  // Saves only if something changed; resolves either way so callers can
  // always chain onto it. Leaves `docDirty` set on failure, so the next
  // blur / Download / Undo retries.
  function saveDoc() {
    if (!docDirty) return Promise.resolve();
    var text = doc.textContent;
    if (!text.trim()) {
      showDocError("The draft can't be empty.");
      return Promise.resolve();
    }
    clearDocError();
    return fetch("/drafts/" + draftId + "/edit", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form({ text: text }),
    })
      .then(function (r) {
        return r.json().then(function (data) {
          return { ok: r.ok, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          showDocError(res.data.error || "Could not save the edit.");
          return;
        }
        docDirty = false;
        undoBtn.disabled = !res.data.can_undo;
        if (res.data.revision_count > revisionCount) {
          addHistory({ instruction: "(manual edit)", note: "" });
        }
        revisionCount = res.data.revision_count;
      })
      .catch(function () {
        showDocError("Could not reach the server. Try again.");
      });
  }

  doc.addEventListener("blur", function () {
    saveDoc();
  });

  if (downloadLink) {
    downloadLink.addEventListener("click", function (e) {
      if (!docDirty) return; // nothing unsaved — let the link navigate as normal
      e.preventDefault();
      saveDoc().then(function () {
        window.location.href = downloadLink.href;
      });
    });
  }

  // "Save to job post": flush a pending manual edit first, then let the
  // form post — same as Download, but a failed flush blocks the submit
  // (the save would otherwise persist stale text into the job post).
  var saveForm = document.getElementById("draft-save-form");
  if (saveForm) {
    saveForm.addEventListener("submit", function (e) {
      if (!docDirty) return;
      e.preventDefault();
      saveDoc().then(function () {
        if (!docDirty) saveForm.submit();
      });
    });
  }

  // --- history -----------------------------------------------------

  function addHistory(entry) {
    if (historyWrap) historyWrap.hidden = false;
    var list = document.getElementById("draft-history");
    if (!list) return;
    var li = document.createElement("li");
    var ins = document.createElement("span");
    ins.className = "draft__history-instruction";
    ins.textContent = entry.instruction;
    li.appendChild(ins);
    if (entry.note) {
      var note = document.createElement("span");
      note.className = "draft__history-note";
      note.textContent = entry.note;
      li.appendChild(note);
    }
    list.appendChild(li);
  }

  // --- helpers ------------------------------------------------------

  function show(el) {
    el.hidden = false;
  }
  function hide(el) {
    el.hidden = true;
  }
  function thousands(n) {
    return (n || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  // Word-level diff: LCS over whitespace-delimited tokens, removals in
  // <del>, additions in <ins>.
  function wordDiff(a, b) {
    var at = a.split(/(\s+)/);
    var bt = b.split(/(\s+)/);
    var n = at.length,
      m = bt.length;
    var lcs = [];
    for (var i = 0; i <= n; i++) lcs.push(new Array(m + 1).fill(0));
    for (i = n - 1; i >= 0; i--) {
      for (var j = m - 1; j >= 0; j--) {
        lcs[i][j] =
          at[i] === bt[j]
            ? lcs[i + 1][j + 1] + 1
            : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
      }
    }
    var out = "";
    i = 0;
    j = 0;
    while (i < n && j < m) {
      if (at[i] === bt[j]) {
        out += escapeHtml(at[i]);
        i++;
        j++;
      } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
        out += at[i].trim() ? "<del>" + escapeHtml(at[i]) + "</del>" : escapeHtml(at[i]);
        i++;
      } else {
        out += bt[j].trim() ? "<ins>" + escapeHtml(bt[j]) + "</ins>" : escapeHtml(bt[j]);
        j++;
      }
    }
    while (i < n) {
      out += at[i].trim() ? "<del>" + escapeHtml(at[i]) + "</del>" : escapeHtml(at[i]);
      i++;
    }
    while (j < m) {
      out += bt[j].trim() ? "<ins>" + escapeHtml(bt[j]) + "</ins>" : escapeHtml(bt[j]);
      j++;
    }
    return out;
  }

  // Listen on the document, not just the <pre>: a drag-select often ends
  // with the mouseup outside the element. Defer a tick so the browser has
  // finalised the selection.
  document.addEventListener("mouseup", function (e) {
    setTimeout(function () {
      onSelectionSettled(e);
    }, 0);
  });
  document.addEventListener("keyup", function (e) {
    if (e.shiftKey || e.key === "Shift" || /^Arrow|Home|End/.test(e.key || "")) {
      setTimeout(function () {
        onSelectionSettled(null);
      }, 0);
    }
  });
  document.addEventListener("mousedown", function (e) {
    if (e.target !== reviseBtn) hide(reviseBtn);
  });
})();
