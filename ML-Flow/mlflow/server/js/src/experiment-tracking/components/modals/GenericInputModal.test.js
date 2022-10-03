import React, { Component } from 'react';
import { shallow } from 'enzyme';
import { GenericInputModal } from './GenericInputModal';
import { Modal } from '@databricks/design-system';

class SimpleForm extends Component {
  render() {
    return null;
  }
}
function validateFields(isFieldValid) {
  if (!isFieldValid) {
    return Promise.reject(new Error("{ formField: 'formValue' }"));
  } else {
    return Promise.resolve({ formField: 'formValue' });
  }
}
function resetFields(resetFieldsFn) {
  resetFieldsFn();
}

describe('GenericInputModal', () => {
  let wrapper;
  let minimalProps;
  let resetFieldsMock;

  beforeEach(() => {
    resetFieldsMock = jest.fn();
    minimalProps = {
      isOpen: false,
      onClose: jest.fn(),
      onCancel: jest.fn(),
      // Mock submission handler that sleeps 1s then resolves
      handleSubmit: (values) =>
        new Promise((resolve) => {
          window.setTimeout(() => {
            resolve();
          }, 1000);
        }),
      title: 'Enter your input',
      children: <SimpleForm shouldValidationThrow={false} resetFieldsFn={resetFieldsMock} />,
    };
    wrapper = shallow(<GenericInputModal {...minimalProps} />);
  });

  test('should render with minimal props without exploding', () => {
    wrapper = shallow(<GenericInputModal {...minimalProps} />);
    expect(wrapper.length).toBe(1);
    expect(wrapper.find(Modal).length).toBe(1);
  });

  test(
    'should validate form contents and set submitting state in submission handler: ' +
      'successful submission case',
    async () => {
      // Test that validateFields() is called, and that handleSubmit is not called
      // when validation fails (and submitting state remains false)
      wrapper = shallow(<GenericInputModal {...minimalProps} />);
      const instance = wrapper.instance();
      wrapper.children(SimpleForm).props().innerRef.current = {
        validateFields: () => validateFields(true),
        resetFields: () => resetFields(resetFieldsMock),
      };
      const onValidationPromise = instance.onSubmit();
      expect(instance.state.isSubmitting).toEqual(true);
      await onValidationPromise;
      // We expect submission to succeed, and for the form fields to be reset and for the form to
      // no longer be submitting
      expect(resetFieldsMock).toBeCalled();
      expect(instance.state.isSubmitting).toEqual(false);
    },
  );

  test(
    'should validate form contents and set submitting state in submission handler: ' +
      'failed validation case',
    async () => {
      // Test that validateFields() is called, and that handleSubmit is not called
      // when validation fails (and submitting state remains false)
      const form = <SimpleForm shouldValidationThrow resetFieldsFn={resetFieldsMock} />;
      const handleSubmit = jest.fn();
      wrapper = shallow(
        <GenericInputModal {...{ ...minimalProps, children: form, handleSubmit }} />,
      );
      const instance = wrapper.instance();
      wrapper.children(SimpleForm).props().innerRef.current = {
        validateFields: () => validateFields(false),
        resetFields: () => resetFields(resetFieldsMock),
      };
      const onValidationPromise = instance.onSubmit();
      expect(instance.state.isSubmitting).toEqual(true);
      try {
        await onValidationPromise;
        // Reported during ESLint upgrade
        // eslint-disable-next-line no-undef
        fail('Must throw');
      } catch (e) {
        // For validation errors, the form should not be reset (so that the user can fix the
        // validation error)
        expect(resetFieldsMock).not.toBeCalled();
        expect(handleSubmit).not.toBeCalled();
        expect(instance.state.isSubmitting).toEqual(false);
      }
    },
  );

  test(
    'should validate form contents and set submitting state in submission handler: ' +
      'failed submission case',
    async () => {
      // Test that validateFields() is called, and that handleSubmit is not called
      // when validation fails (and submitting state remains false)
      const form = <SimpleForm shouldValidationThrow={false} resetFieldsFn={resetFieldsMock} />;
      const handleSubmit = (values) =>
        new Promise((resolve, reject) => {
          window.setTimeout(() => {
            reject(new Error());
          }, 1000);
        });
      wrapper = shallow(
        <GenericInputModal {...{ ...minimalProps, children: form, handleSubmit }} />,
      );
      const instance = wrapper.instance();
      wrapper.children(SimpleForm).props().innerRef.current = {
        validateFields: () => validateFields(true),
        resetFields: () => resetFields(resetFieldsMock),
      };
      const onValidationPromise = instance.onSubmit();
      expect(instance.state.isSubmitting).toEqual(true);
      await onValidationPromise;
      // For validation errors, the form should not be reset (so that the user can fix the
      // validation error)
      expect(resetFieldsMock).toBeCalled();
      expect(instance.state.isSubmitting).toEqual(false);
    },
  );
});
