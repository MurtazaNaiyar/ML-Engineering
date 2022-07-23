import { configure } from 'enzyme';
import Adapter from '@wojtekmaj/enzyme-adapter-react-17';

configure({ adapter: new Adapter() });
// Included to mock local storage in JS tests, see docs at
// https://www.npmjs.com/package/jest-localstorage-mock#in-create-react-app
require('jest-localstorage-mock');

global.setImmediate = (cb) => {
  return setTimeout(cb, 0);
};
global.clearImmediate = (id) => {
  return clearTimeout(id);
};

// for plotly.js to work
//
window.URL.createObjectURL = function createObjectURL() {};

// Mock loadMessages which uses require.context from webpack which is unavailable in node.
jest.mock('./i18n/loadMessages', () => ({
  __esModule: true,
  DEFAULT_LOCALE: 'en',
  loadMessages: async (locale) => {
    if (locale.endsWith('unknown')) {
      return {};
    }
    return {
      // top-locale helps us see which merged message file has top precedence
      'top-locale': locale,
      [locale]: 'value',
    };
  },
}));

beforeEach(() => {
  // Prevent unit tests making actual fetch calls,
  // every test should explicitly mock all the API calls for the tested component.
  global.fetch = jest.fn(() => {
    throw new Error(
      'No API calls should be made from unit tests. Please explicitly mock all API calls.',
    );
  });
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: jest.fn().mockImplementation((query) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
});
