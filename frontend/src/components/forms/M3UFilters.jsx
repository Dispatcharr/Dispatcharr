import M3URulesModal from './M3URulesModal.jsx';

const M3UFilters = ({
  playlist,
  isOpen,
  onClose,
  onRulesChanged,
  previewGroupIds,
}) => (
  <M3URulesModal
    opened={isOpen && !!playlist?.id}
    onClose={onClose}
    title="Stream filters"
    accountId={playlist?.id}
    accountType={playlist?.account_type}
    streamFilters
    previewGroupIds={previewGroupIds}
    onRulesChanged={onRulesChanged}
  />
);

export default M3UFilters;
