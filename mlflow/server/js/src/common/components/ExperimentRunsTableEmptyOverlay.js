import React, { Component } from 'react';
import { LoggingRunsDocUrl } from '../constants';
import { FormattedMessage } from 'react-intl';

/**
 * Display a helper overlay to on board new users on MLflow when the experiments runs table is
 * empty.
 */
export class ExperimentRunsTableEmptyOverlay extends Component {
  getLearnMoreLinkUrl = () => LoggingRunsDocUrl;

  render() {
    const learnMoreLinkUrl = this.getLearnMoreLinkUrl();
    return (
      <div className='experiment-runs-table-empty-overlay' css={classNames.wrapper}>
        <span>
          <FormattedMessage
            // eslint-disable-next-line max-len
            defaultMessage='No runs yet. <link>Learn more</link> about how to create ML model training {newLine} runs in this experiment.'
            // eslint-disable-next-line max-len
            description='Empty state text for experiment runs page'
            values={{
              link: (chunks) => (
                // Reported during ESLint upgrade
                // eslint-disable-next-line react/jsx-no-target-blank
                <a target='_blank' href={learnMoreLinkUrl}>
                  {chunks}
                </a>
              ),
              newLine: <br />,
            }}
          />
        </span>
      </div>
    );
  }
}

const classNames = {
  wrapper: {
    position: 'relative',
    top: '10px',
    fontSize: '13px',
    padding: '30px',
    width: '100 %',
    pointerEvents: 'all',
  },
};
