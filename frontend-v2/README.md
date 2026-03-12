# DCMS Evidence Bot — Frontend v2

React + Tailwind CSS frontend for the DCMS Evidence Bot legal Q&A system.

## Prerequisites

- Node.js 18+
- Backend running at `http://localhost:8000`

## Setup

```bash
cd frontend-v2
npm install
npm run dev
```

Opens at `http://localhost:5173`. API requests are proxied to the backend via Vite's dev server.

## Production Build

```bash
npm run build
npm run preview
```

## Architecture

```
src/
├── App.jsx                 # Root component, state management
├── main.jsx                # Entry point
├── index.css               # Tailwind config + prose styles
├── components/
│   ├── Header.jsx          # Title, theme toggle, settings button
│   ├── SearchInput.jsx     # Query input with loading state
│   ├── EmptyState.jsx      # Example questions shown before first query
│   ├── LoadingSkeleton.jsx # Animated skeleton while loading
│   ├── AnswerPanel.jsx     # Rendered markdown answer with citations
│   ├── ConfidenceBadge.jsx # Dot indicator for confidence level
│   ├── SourceCard.jsx      # Expandable source citation card
│   ├── SourcesList.jsx     # Container for source cards
│   ├── RefusalMessage.jsx  # Insufficient evidence / refusal display
│   ├── ErrorMessage.jsx    # Network/backend error display
│   └── SettingsDrawer.jsx  # Filters, theme, developer tools
├── hooks/
│   └── useTheme.js         # Dark/light mode with localStorage
└── lib/
    ├── api.js              # Backend API client
    └── citations.js        # Citation parsing and superscript conversion
```

## Features

- Dark/light mode (persisted in localStorage)
- Markdown rendering with inline citation superscripts
- Clickable citations that scroll to and highlight source cards
- Source filter controls (primary legislation, guidance, debates)
- Developer tools panel (KB inventory, retrieval debug)
- Loading skeleton, error, and refusal states
