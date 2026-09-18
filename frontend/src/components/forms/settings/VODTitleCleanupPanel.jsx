import React from 'react';
import VODMetadataModal from '../../VODMetadataModal.jsx';

const VODTitleCleanupPanel = ({ active = true }) =>
  active ? (
    <VODMetadataModal opened embedded settingsSection="title-cleanup" />
  ) : null;

export default VODTitleCleanupPanel;
