import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Button } from '../../shared/building_blocks/Button';

export const TrimmedText = ({ text, maxSize, className, allowShowMore = false }) => {
  if (text.length <= maxSize) {
    return <span className={className}>{text}</span>;
  }
  const trimmedText = `${text.substr(0, maxSize)}...`;
  // Reported during ESLint upgrade
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const [showMore, setShowMore] = useState(false);
  return (
    <span className={className}>
      {showMore ? text : trimmedText}
      {allowShowMore && (
        <Button
          type='link'
          onClick={() => setShowMore(!showMore)}
          size='small'
          css={styles.expandButton}
          data-test-id='trimmed-text-button'
        >
          {showMore ? 'collapse' : 'expand'}
        </Button>
      )}
    </span>
  );
};

const styles = {
  expandButton: {
    display: 'inline-block',
  },
};

TrimmedText.propTypes = {
  text: PropTypes.string.isRequired,
  maxSize: PropTypes.number.isRequired,
  className: PropTypes.string.isRequired,
  allowShowMore: PropTypes.bool,
};
