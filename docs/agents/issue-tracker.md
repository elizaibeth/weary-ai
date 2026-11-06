# Issue tracker: GitHub Issues

Issues and specs for this repo live in GitHub Issues on `elizaibeth/weary-ai`. Use the `gh` CLI.

## Conventions

- One issue per ticket. A feature with several tickets gets a parent spec issue; each ticket links it with `Parent: #<number>` at the top of its body.
- Triage state is a label (see `triage-labels.md`).
- Conversation goes in issue comments.
- A pull request that completes a ticket says `Closes #<number>` in its description.

## When a skill says "publish to the issue tracker"

`gh issue create --title "<outcome-focused title>" --body-file <file> --label needs-triage`

## When a skill says "fetch the relevant ticket"

`gh issue view <number> --comments`

## Wayfinding operations

Used by `/wayfinder`. The **map** is a parent issue with one **child** issue per ticket.

- **Map**: an issue labelled `map`, whose body holds Notes / Decisions so far / Fog.
- **Child ticket**: an issue with `Parent: #<map>` and `Type: research|prototype|grilling|task` at the top of its body, and the question below.
- **Blocking**: a `Blocked by: #N, #N` line in the body. A ticket is unblocked when every listed issue is closed.
- **Frontier**: open, unblocked issues with no assignee and `Parent: #<map>`; the lowest number wins.
- **Claim**: assign yourself (`gh issue edit <n> --add-assignee @me`) before any work.
- **Resolve**: comment the answer under an `## Answer` heading, close the issue, then add a one-line pointer (gist and link) to the map's Decisions so far.
