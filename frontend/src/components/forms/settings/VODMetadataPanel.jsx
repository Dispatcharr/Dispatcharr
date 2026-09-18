import React from 'react';
import VODMetadataModal from '../../VODMetadataModal.jsx';

const VODMetadataPanel = ({ active = true }) =>
  active ? (
    <VODMetadataModal opened embedded settingsSection="metadata" />
  ) : null;

export default VODMetadataPanel;
