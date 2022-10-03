import React, { Component } from 'react';
import PropTypes from 'prop-types';
import RequestStateWrapper from '../../common/components/RequestStateWrapper';
import { getExperimentApi, getRunApi, setTagApi } from '../actions';
import { searchModelVersionsApi } from '../../model-registry/actions';
import { connect } from 'react-redux';
import { RunView } from './RunView';
import Routes from '../routes';
import Utils from '../../common/utils/Utils';
import { ErrorCodes } from '../../common/constants';
import { RunNotFoundView } from './RunNotFoundView';
import { getUUID } from '../../common/utils/ActionUtils';
import { Spinner } from '../../common/components/Spinner';
import { PageContainer } from '../../common/components/PageContainer';

export class RunPageImpl extends Component {
  static propTypes = {
    runUuid: PropTypes.string.isRequired,
    experimentId: PropTypes.string.isRequired,
    modelVersions: PropTypes.arrayOf(PropTypes.object),
    getRunApi: PropTypes.func.isRequired,
    getExperimentApi: PropTypes.func.isRequired,
    searchModelVersionsApi: PropTypes.func.isRequired,
    setTagApi: PropTypes.func.isRequired,
  };

  getRunRequestId = getUUID();

  getExperimentRequestId = getUUID();

  searchModelVersionsRequestId = getUUID();

  setTagRequestId = getUUID();

  componentDidMount() {
    const { experimentId, runUuid } = this.props;
    this.props.getRunApi(runUuid, this.getRunRequestId);
    this.props.getExperimentApi(experimentId, this.getExperimentRequestId);
    this.props.searchModelVersionsApi({ run_id: runUuid }, this.searchModelVersionsRequestId);
  }

  handleSetRunTag = (tagName, value) => {
    const { runUuid } = this.props;
    return this.props
      .setTagApi(runUuid, tagName, value, this.setTagRequestId)
      .then(() => getRunApi(runUuid, this.getRunRequestId));
  };

  renderRunView = (isLoading, shouldRenderError, requests) => {
    if (isLoading) {
      return <Spinner />;
    } else if (shouldRenderError) {
      const getRunRequest = Utils.getRequestWithId(requests, this.getRunRequestId);
      if (getRunRequest.error.getErrorCode() === ErrorCodes.RESOURCE_DOES_NOT_EXIST) {
        return <RunNotFoundView runId={this.props.runUuid} />;
      }
      return null;
    }
    return (
      <RunView
        runUuid={this.props.runUuid}
        getMetricPagePath={(key) =>
          Routes.getMetricPageRoute([this.props.runUuid], key, [this.props.experimentId])
        }
        experimentId={this.props.experimentId}
        modelVersions={this.props.modelVersions}
        handleSetRunTag={this.handleSetRunTag}
      />
    );
  };

  render() {
    const requestIds = [this.getRunRequestId, this.getExperimentRequestId];
    return (
      <PageContainer>
        <RequestStateWrapper
          requestIds={requestIds}
          // eslint-disable-next-line no-trailing-spaces
        >
          {this.renderRunView}
        </RequestStateWrapper>
      </PageContainer>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { match } = ownProps;
  const { runUuid, experimentId } = match.params;
  const { modelVersionsByRunUuid } = state.entities;
  const modelVersions = modelVersionsByRunUuid ? modelVersionsByRunUuid[runUuid] : null;
  return {
    runUuid,
    experimentId,
    modelVersions,
    // so that we re-render the component when the route changes
    key: runUuid + experimentId,
  };
};

const mapDispatchToProps = {
  getRunApi,
  getExperimentApi,
  searchModelVersionsApi,
  setTagApi,
};

export const RunPage = connect(mapStateToProps, mapDispatchToProps)(RunPageImpl);
