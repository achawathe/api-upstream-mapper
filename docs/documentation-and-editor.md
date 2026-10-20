# Documentation context and visual mapping editor

The Inputs screen accepts optional documentation for either API: pasted text or
PDF, DOCX, TXT and Markdown files. Attach it to the relevant specification and,
optionally, a single endpoint. A document can cover several endpoints using
headings such as `GET /inventory`. Field definitions should mention the actual
field name or path. Ambiguous unscoped field names are excluded instead of being
applied to every endpoint.

Supporting docs describe the API itself: field meanings, units, formats, values and behavior.
They do not need to say how to map to another API. The mapper makes suggestions from
these definitions; explicit mapping choices belong in the editor.

Extraction and inference stay local. PDF support requires selectable text; scanned
pages need OCR outside this app. Documents supply context, not executable
instructions, new schema fields, or model-weight training. Extracted passages
retain file/page/paragraph references. Supported definitions participate in local
semantic matching and purpose checks, with citations in candidate evidence.
Document-assisted suggestions require review.

Choose **General applications** in the vocabulary settings for nonfinancial APIs.
Finance remains the default for existing workspaces. An extra vocabulary can extend
either choice.

## Editing mappings

The Blocks view groups output fields by endpoint or a reviewer-assigned category.
Select an output, then connect a source from the palette by dragging it into the
source slot or pressing **Connect source**. The source, conversion steps and output
appear in order with arrows between them. This is a focused block composer, not
an unrestricted programming canvas.

Conversion blocks support type changes, value translations, decimal shifts and
existing date/time conversions. Add, remove or reorder steps; arrow buttons provide
an alternative to dragging. **Try a value before saving** executes the conversions
and checks that one example against the output field. This does not prove that
every production value will convert correctly.

Save explicitly to record a manual mapping. Discard draft restores the saved state;
Restore suggestion removes the manual override. Categories, notes and conversion
steps persist across runs. Categories are also exported to Excel. The existing
Table view remains available for scanning larger sets of mappings.

## Design rationale and validation limits

Visible drop targets and drag handles follow the usability guidance in
[Nielsen Norman Group's drag-and-drop recommendations](https://www.nngroup.com/articles/drag-drop/).
Connect and move buttons provide the alternative to dragging described in
[WCAG 2.2 dragging movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements/).
Endpoint/category grouping and collapsed evidence keep the active mapping in focus.

Browser checks cover document pasting, a local-model run, source selection,
conversion addition/reordering/removal through buttons, value preview, saving and
category grouping. Pointer checks in the in-app browser also verify source drops
and conversion reordering in both directions. Smaller layouts place the source
palette above the connection area so both can be reached without crossing the
entire mapping. Conversion targets highlight during dragging. A formal accessibility
audit and timed user study remain outstanding; faster editing has not been measured.

Three small development cases span weather, inventory and shipments. With the real
local MiniLM model, cited definitions recovered 3/3 renamed fields; without the
definitions, 0/3 were recovered. The inventory case converts a documented numeric
string into an integer. All three remain review suggestions. These deliberately
small cases verify the feature path; similar wording in their definitions makes
them unsuitable evidence of broad model accuracy.
