import React, { useState } from 'react';
import { Button, Form, Input, Select, message } from 'antd';
import axios from 'axios';

const { Option } = Select;

const ProxyManager = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (values) => {
    setLoading(true);
    try {
      const { action, ...data } = values;
      await axios.post(`/proxy/api/proxy/${action}/`, data);
      message.success(`Proxy ${action} successful`);
      form.resetFields();
    } catch (error) {
      message.error(error.response?.data?.error || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="proxy-manager">
      <h2>Proxy Manager</h2>
      <Form form={form} onFinish={handleSubmit} layout="vertical">
        <Form.Item
          name="type"
          label="Proxy Type"
          rules={[{ required: true }]}
        >
          <Select>
            <Option value="hls">HLS</Option>
            <Option value="ts">TS</Option>
          </Select>
        </Form.Item>

        <Form.Item
          name="channel"
          label="Channel ID"
          rules={[{ required: true }]}
        >
          <Input />
        </Form.Item>

        <Form.Item
          name="url"
          label="Stream URL"
          rules={[{ required: true, type: 'url' }]}
        >
          <Input />
        </Form.Item>

        <Form.Item>
          <Button.Group>
            <Button
              type="primary"
              onClick={() => form.submit()}
              loading={loading}
            >
              Start Proxy
            </Button>
            <Button
              danger
              onClick={() => {
                form.setFieldsValue({ action: 'stop' });
                form.submit();
              }}
              loading={loading}
            >
              Stop Proxy
            </Button>
          </Button.Group>
        </Form.Item>
      </Form>
    </div>
  );
};

export default ProxyManager;