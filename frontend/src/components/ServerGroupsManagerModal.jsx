import { Modal } from '@mantine/core';
import ServerGroupsTable from './tables/ServerGroupsTable';

const ServerGroupsManagerModal = ({
  isOpen,
  onClose,
  onGroupCreated,
  openCreateOnMount = false,
}) => {
  return (
    <Modal
      opened={isOpen}
      onClose={onClose}
      title="Server Groups"
      size="lg"
      centered
    >
      {isOpen ? (
        <ServerGroupsTable
          onGroupCreated={onGroupCreated}
          openCreateOnMount={openCreateOnMount}
        />
      ) : null}
    </Modal>
  );
};

export default ServerGroupsManagerModal;
