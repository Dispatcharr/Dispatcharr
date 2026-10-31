import { useState } from 'react';
import ErrorBoundary from './ErrorBoundary.jsx';
import LibraryWorkspace from './LibraryWorkspace.jsx';
import LibraryPreviewModal from './LibraryPreviewModal.jsx';
import useLibraryStore from '../store/useLibraryStore';

// Load the workspace and preview together, before a title can be opened.
export default function LibraryView({ view, displayMode }) {
  const [preview, setPreview] = useState(null);
  const openPreview = (item) =>
    setPreview({
      item,
      accountId: useLibraryStore.getState().filters.account || '',
    });
  return (
    <LibraryWorkspace
      view={view}
      displayMode={displayMode}
      onPreview={openPreview}
    >
      {preview && (
        <ErrorBoundary inline>
          <LibraryPreviewModal
            inStack
            key={`${preview.item.content_type}:${preview.item.content_id}:${preview.item.source_id || ''}`}
            item={preview.item}
            accountId={preview.accountId}
            onClose={() => setPreview(null)}
          />
        </ErrorBoundary>
      )}
    </LibraryWorkspace>
  );
}
