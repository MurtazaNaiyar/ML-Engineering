import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import CompareRunPage from './CompareRunPage';
import { Provider } from 'react-redux';
import configureStore from 'redux-mock-store';
import thunk from 'redux-thunk';
import promiseMiddleware from 'redux-promise-middleware';

import { mountWithIntl } from '../../common/utils/TestUtils';

describe('CompareRunPage', () => {
  let wrapper;
  let minimalProps;
  let minimalStore;
  const mockStore = configureStore([thunk, promiseMiddleware()]);

  beforeEach(() => {
    // TODO: remove global fetch mock by explicitly mocking all the service API calls
    global.fetch = jest.fn(() =>
      Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve('') }),
    );
    minimalProps = {
      location: {
        search: {
          '?runs': '["runn-1234-5678-9012", "runn-1234-5678-9034"]',
          experiments: '["12345"]',
        },
      },
      experimentIds: ['12345'],
      runUuids: ['runn-1234-5678-9012', 'runn-1234-5678-9034'],
      dispatch: jest.fn(),
    };
    minimalStore = mockStore({
      entities: {},
      apis: jest.fn((key) => {
        return {};
      }),
    });
  });

  test('should render with minimal props without exploding', () => {
    wrapper = mountWithIntl(
      <Provider store={minimalStore}>
        <BrowserRouter>
          <CompareRunPage {...minimalProps} />
        </BrowserRouter>
      </Provider>,
    );
    expect(wrapper.find(CompareRunPage).length).toBe(1);
  });
});
