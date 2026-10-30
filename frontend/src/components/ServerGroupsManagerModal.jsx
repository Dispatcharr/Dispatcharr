import StackedModal from './StackedModal.jsx';
import ServerGroupsTable from './tables/ServerGroupsTable';

const ServerGroupsManagerModal = ({
  isOpen,
  onClose,
  onGroupCreated,
  openCreateOnMount = false,
}) => {
  return (
    <StackedModal
      stackId="m3u-server-groups"
      opened={isOpen}
      onClose={onClose}
      title="Server Groups"
      size="md"
      centered
    >
      {isOpen ? (
        <ServerGroupsTable
          onGroupCreated={onGroupCreated}
          openCreateOnMount={openCreateOnMount}
        />
      ) : null}
    </StackedModal>
  );
};

export default ServerGroupsManagerModal;
