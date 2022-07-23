import React, { Component } from 'react';
import PropTypes from 'prop-types';
import { connect } from 'react-redux';
import { withRouter } from 'react-router';
import { injectIntl, FormattedMessage } from 'react-intl';
import { Tooltip, Switch } from 'antd';
import { Tabs } from '@databricks/design-system';

import { getExperiment, getParams, getRunInfo, getRunTags } from '../reducers/Reducers';
import './CompareRunView.css';
import { Experiment, RunInfo } from '../sdk/MlflowMessages';
import { CompareRunScatter } from './CompareRunScatter';
import CompareRunContour from './CompareRunContour';
import Routes from '../routes';
import { Link } from 'react-router-dom';
import { getLatestMetrics } from '../reducers/MetricReducer';
import CompareRunUtil from './CompareRunUtil';
import Utils from '../../common/utils/Utils';
import ParallelCoordinatesPlotPanel from './ParallelCoordinatesPlotPanel';
import { PageHeader } from '../../shared/building_blocks/PageHeader';
import { CollapsibleSection } from '../../common/components/CollapsibleSection';

const { TabPane } = Tabs;

export class CompareRunView extends Component {
  static propTypes = {
    experiments: PropTypes.arrayOf(PropTypes.instanceOf(Experiment)).isRequired,
    experimentIds: PropTypes.arrayOf(PropTypes.string).isRequired,
    comparedExperimentIds: PropTypes.arrayOf(PropTypes.string),
    hasComparedExperimentsBefore: PropTypes.bool,
    runInfos: PropTypes.arrayOf(PropTypes.instanceOf(RunInfo)).isRequired,
    runUuids: PropTypes.arrayOf(PropTypes.string).isRequired,
    metricLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    paramLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    tagLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    // Array of user-specified run names. Elements may be falsy (e.g. empty string or undefined) if
    // a run was never given a name.
    runNames: PropTypes.arrayOf(PropTypes.string).isRequired,
    // Array of names to use when displaying runs. No element in this array should be falsy;
    // we expect this array to contain user-specified run names, or default display names
    // ("Run <uuid>") for runs without names.
    runDisplayNames: PropTypes.arrayOf(PropTypes.string).isRequired,
    intl: PropTypes.shape({ formatMessage: PropTypes.func.isRequired }).isRequired,
  };

  constructor(props) {
    super(props);
    this.state = {
      tableWidth: null,
      onlyShowParamDiff: false,
      onlyShowMetricDiff: false,
    };
    this.onResizeHandler = this.onResizeHandler.bind(this);
    this.onCompareRunTableScrollHandler = this.onCompareRunTableScrollHandler.bind(this);

    this.runDetailsTableRef = React.createRef();
    this.compareRunViewRef = React.createRef();
  }

  onResizeHandler(e) {
    const table = this.runDetailsTableRef.current;
    if (table !== null) {
      const containerWidth = table.clientWidth;
      this.setState({ tableWidth: containerWidth });
    }
  }

  onCompareRunTableScrollHandler(e) {
    const blocks = this.compareRunViewRef.current.querySelectorAll('.compare-run-table');
    blocks.forEach((_, index) => {
      const block = blocks[index];
      if (block !== e.target) {
        block.scrollLeft = e.target.scrollLeft;
      }
    });
  }

  componentDidMount() {
    const pageTitle = this.props.intl.formatMessage(
      {
        description: 'Page title for the compare runs page',
        defaultMessage: 'Comparing {runs} MLflow Runs',
      },
      {
        runs: this.props.runInfos.length,
      },
    );
    Utils.updatePageTitle(pageTitle);

    window.addEventListener('resize', this.onResizeHandler, true);
    window.dispatchEvent(new Event('resize'));
  }

  componentWillUnmount() {
    // Avoid registering `onResizeHandler` every time this component mounts
    window.removeEventListener('resize', this.onResizeHandler, true);
  }

  getTableColumnWidth() {
    const minColWidth = 200;
    let colWidth = minColWidth;

    if (this.state.tableWidth !== null) {
      colWidth = Math.round(this.state.tableWidth / (this.props.runInfos.length + 1));
      if (colWidth < minColWidth) {
        colWidth = minColWidth;
      }
    }
    return colWidth;
  }

  renderExperimentNameRowItems() {
    const { experiments } = this.props;
    const experimentNameMap = Utils.getExperimentNameMap(Utils.sortExperimentsById(experiments));
    return this.props.runInfos.map(({ experiment_id, run_uuid }) => {
      const { name, basename } = experimentNameMap[experiment_id];
      return (
        <td className='meta-info' key={run_uuid}>
          <Link to={Routes.getExperimentPageRoute(experiment_id)} title={name}>
            {basename}
          </Link>
        </td>
      );
    });
  }

  hasMultipleExperiments() {
    return this.props.experimentIds.length > 1;
  }

  shouldShowExperimentNameRow() {
    return this.props.hasComparedExperimentsBefore || this.hasMultipleExperiments();
  }

  getExperimentPageLink(experimentId, experimentName) {
    return <Link to={Routes.getExperimentPageRoute(experimentId)}>{experimentName}</Link>;
  }

  getCompareExperimentsPageLinkText(numExperiments) {
    return (
      <FormattedMessage
        defaultMessage='Displaying Runs from {numExperiments} Experiments'
        // eslint-disable-next-line max-len
        description='Breadcrumb nav item to link to compare-experiments page on compare runs page'
        values={{ numExperiments }}
      />
    );
  }

  getCompareExperimentsPageLink(experimentIds) {
    return (
      <Link to={Routes.getCompareExperimentsPageRoute(experimentIds)}>
        {this.getCompareExperimentsPageLinkText(experimentIds.length)}
      </Link>
    );
  }

  getExperimentLink() {
    const { comparedExperimentIds, hasComparedExperimentsBefore, experimentIds, experiments } =
      this.props;

    if (hasComparedExperimentsBefore) {
      return this.getCompareExperimentsPageLink(comparedExperimentIds);
    }

    if (this.hasMultipleExperiments()) {
      return this.getCompareExperimentsPageLink(experimentIds);
    }

    return this.getExperimentPageLink(experimentIds[0], experiments[0].name);
  }

  getTitle() {
    return this.hasMultipleExperiments() ? (
      <FormattedMessage
        defaultMessage='Comparing {numRuns} Runs from {numExperiments} Experiments'
        // eslint-disable-next-line max-len
        description='Breadcrumb title for compare runs page with multiple experiments'
        values={{
          numRuns: this.props.runInfos.length,
          numExperiments: this.props.experimentIds.length,
        }}
      />
    ) : (
      <FormattedMessage
        defaultMessage='Comparing {numRuns} Runs from 1 Experiment'
        description='Breadcrumb title for compare runs page with single experiment'
        values={{
          numRuns: this.props.runInfos.length,
        }}
      />
    );
  }

  renderParamTable(colWidth) {
    const dataRows = this.renderDataRows(
      this.props.paramLists,
      colWidth,
      this.state.onlyShowParamDiff,
      true,
    );
    if (dataRows.length === 0) {
      return (
        <h2>
          <FormattedMessage
            defaultMessage='No parameters to display.'
            description='Text shown when there are no parameters to display'
          />
        </h2>
      );
    }
    return (
      <table
        className='table compare-table compare-run-table'
        css={{ maxHeight: '500px' }}
        onScroll={this.onCompareRunTableScrollHandler}
      >
        <tbody>{dataRows}</tbody>
      </table>
    );
  }

  renderMetricTable(colWidth, experimentIds) {
    const dataRows = this.renderDataRows(
      this.props.metricLists,
      colWidth,
      this.state.onlyShowMetricDiff,
      false,
      (key, data) => {
        return (
          <Link
            to={Routes.getMetricPageRoute(
              this.props.runInfos
                .map((info) => info.run_uuid)
                .filter((uuid, idx) => data[idx] !== undefined),
              key,
              experimentIds,
            )}
            title='Plot chart'
          >
            {key}
            <i className='fas fa-chart-line' css={{ paddingLeft: '6px' }} />
          </Link>
        );
      },
      Utils.formatMetric,
    );
    if (dataRows.length === 0) {
      return (
        <h2>
          <FormattedMessage
            defaultMessage='No metrics to display.'
            description='Text shown when there are no metrics to display'
          />
        </h2>
      );
    }
    return (
      <table
        className='table compare-table compare-run-table'
        css={{ maxHeight: '300px' }}
        onScroll={this.onCompareRunTableScrollHandler}
      >
        <tbody>{dataRows}</tbody>
      </table>
    );
  }

  renderTagTable(colWidth) {
    const dataRows = this.renderDataRows(
      this.props.tagLists,
      colWidth,
      this.state.onlyShowParamDiff,
      true,
    );
    if (dataRows.length === 0) {
      return (
        <h2>
          <FormattedMessage
            defaultMessage='No tags to display.'
            description='Text shown when there are no tags to display'
          />
        </h2>
      );
    }
    return (
      <table
        className='table compare-table compare-run-table'
        css={{ maxHeight: '500px' }}
        onScroll={this.onCompareRunTableScrollHandler}
      >
        <tbody>{dataRows}</tbody>
      </table>
    );
  }

  renderTimeRows(colWidthStyle) {
    const unknown = (
      <FormattedMessage
        defaultMessage='(unknown)'
        description="Filler text when run's time information is unavailable"
      />
    );
    const getTimeAttributes = (runInfo) => {
      const startTime = runInfo.getStartTime();
      const endTime = runInfo.getEndTime();
      return {
        runUuid: runInfo.run_uuid,
        startTime: startTime ? Utils.formatTimestamp(startTime) : unknown,
        endTime: endTime ? Utils.formatTimestamp(endTime) : unknown,
        duration: startTime && endTime ? Utils.getDuration(startTime, endTime) : unknown,
      };
    };
    const timeAttributes = this.props.runInfos.map(getTimeAttributes);
    const rows = [
      {
        key: 'startTime',
        title: (
          <FormattedMessage
            defaultMessage='Start Time:'
            description='Row title for the start time of runs on the experiment compare runs page'
          />
        ),
        data: timeAttributes.map(({ runUuid, startTime }) => [runUuid, startTime]),
      },
      {
        key: 'endTime',
        title: (
          <FormattedMessage
            defaultMessage='End Time:'
            description='Row title for the end time of runs on the experiment compare runs page'
          />
        ),
        data: timeAttributes.map(({ runUuid, endTime }) => [runUuid, endTime]),
      },
      {
        key: 'duration',
        title: (
          <FormattedMessage
            defaultMessage='Duration:'
            description='Row title for the duration of runs on the experiment compare runs page'
          />
        ),
        data: timeAttributes.map(({ runUuid, duration }) => [runUuid, duration]),
      },
    ];
    return rows.map(({ key, title, data }) => (
      <tr key={key}>
        <th scope='row' className='head-value sticky-header' css={colWidthStyle}>
          {title}
        </th>
        {data.map(([runUuid, value]) => (
          <td className='data-value' key={runUuid} css={colWidthStyle}>
            <Tooltip
              title={value}
              color='gray'
              placement='topLeft'
              overlayStyle={{ maxWidth: '400px' }}
              mouseEnterDelay={1.0}
            >
              {value}
            </Tooltip>
          </td>
        ))}
      </tr>
    ));
  }

  render() {
    const { experimentIds } = this.props;
    const { runInfos, runNames } = this.props;

    const colWidth = this.getTableColumnWidth();
    const colWidthStyle = this.genWidthStyle(colWidth);

    const title = this.getTitle();
    /* eslint-disable-next-line prefer-const */
    let breadcrumbs = [this.getExperimentLink(), title];
    return (
      <div className='CompareRunView' ref={this.compareRunViewRef}>
        <PageHeader title={title} breadcrumbs={breadcrumbs} />
        <CollapsibleSection
          title={this.props.intl.formatMessage({
            defaultMessage: 'Visualizations',
            description: 'Tabs title for plots on the compare runs page',
          })}
        >
          <Tabs>
            <TabPane
              tab={
                <FormattedMessage
                  defaultMessage='Parallel Coordinates Plot'
                  // eslint-disable-next-line max-len
                  description='Tab pane title for parallel coordinate plots on the compare runs page'
                />
              }
              key='1'
            >
              <ParallelCoordinatesPlotPanel runUuids={this.props.runUuids} />
            </TabPane>
            <TabPane
              tab={
                <FormattedMessage
                  defaultMessage='Scatter Plot'
                  description='Tab pane title for scatterplots on the compare runs page'
                />
              }
              key='2'
            >
              <CompareRunScatter
                runUuids={this.props.runUuids}
                runDisplayNames={this.props.runDisplayNames}
              />
            </TabPane>
            <TabPane
              tab={
                <FormattedMessage
                  defaultMessage='Contour Plot'
                  description='Tab pane title for contour plots on the compare runs page'
                />
              }
              key='3'
            >
              <CompareRunContour
                runUuids={this.props.runUuids}
                runDisplayNames={this.props.runDisplayNames}
              />
            </TabPane>
          </Tabs>
        </CollapsibleSection>
        <CollapsibleSection
          title={this.props.intl.formatMessage({
            defaultMessage: 'Run details',
            description: 'Compare table title on the compare runs page',
          })}
        >
          <table
            className='table compare-table compare-run-table'
            ref={this.runDetailsTableRef}
            onScroll={this.onCompareRunTableScrollHandler}
          >
            <thead>
              <tr>
                <th scope='row' className='head-value sticky-header' css={colWidthStyle}>
                  <FormattedMessage
                    defaultMessage='Run ID:'
                    description='Row title for the run id on the experiment compare runs page'
                  />
                </th>
                {this.props.runInfos.map((r) => (
                  <th scope='row' className='data-value' key={r.run_uuid} css={colWidthStyle}>
                    <Tooltip
                      title={r.getRunUuid()}
                      color='gray'
                      placement='topLeft'
                      overlayStyle={{ maxWidth: '400px' }}
                      mouseEnterDelay={1.0}
                    >
                      <Link to={Routes.getRunPageRoute(r.getExperimentId(), r.getRunUuid())}>
                        {r.getRunUuid()}
                      </Link>
                    </Tooltip>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope='row' className='head-value sticky-header' css={colWidthStyle}>
                  <FormattedMessage
                    defaultMessage='Run Name:'
                    description='Row title for the run name on the experiment compare runs page'
                  />
                </th>
                {runNames.map((runName, i) => {
                  return (
                    <td className='data-value' key={runInfos[i].run_uuid} css={colWidthStyle}>
                      <div className='truncate-text single-line'>
                        <Tooltip
                          title={runName}
                          color='gray'
                          placement='topLeft'
                          overlayStyle={{ maxWidth: '400px' }}
                          mouseEnterDelay={1.0}
                        >
                          {runName}
                        </Tooltip>
                      </div>
                    </td>
                  );
                })}
              </tr>
              {this.renderTimeRows(colWidthStyle)}
              {this.shouldShowExperimentNameRow() && (
                <tr>
                  <th scope='row' className='data-value'>
                    <FormattedMessage
                      defaultMessage='Experiment Name:'
                      // eslint-disable-next-line max-len
                      description='Row title for the experiment IDs of runs on the experiment compare runs page'
                    />
                  </th>
                  {this.renderExperimentNameRowItems()}
                </tr>
              )}
            </tbody>
          </table>
        </CollapsibleSection>
        <CollapsibleSection
          title={this.props.intl.formatMessage({
            defaultMessage: 'Parameters',
            description:
              'Row group title for parameters of runs on the experiment compare runs page',
          })}
        >
          <Switch
            checkedChildren='Show diff only'
            unCheckedChildren='Show diff only'
            onChange={(checked, e) => this.setState({ onlyShowParamDiff: checked })}
          />
          <br />
          <br />
          {this.renderParamTable(colWidth)}
        </CollapsibleSection>
        <CollapsibleSection
          title={this.props.intl.formatMessage({
            defaultMessage: 'Metrics',
            description: 'Row group title for metrics of runs on the experiment compare runs page',
          })}
        >
          <Switch
            checkedChildren='Show diff only'
            unCheckedChildren='Show diff only'
            onChange={(checked, e) => this.setState({ onlyShowMetricDiff: checked })}
          />
          <br />
          <br />
          {this.renderMetricTable(colWidth, experimentIds)}
        </CollapsibleSection>
        <CollapsibleSection
          title={this.props.intl.formatMessage({
            defaultMessage: 'Tags',
            description: 'Row group title for tags of runs on the experiment compare runs page',
          })}
        >
          <Switch
            checkedChildren='Show diff only'
            unCheckedChildren='Show diff only'
            onChange={(checked, e) => this.setState({ onlyShowParamDiff: checked })}
          />
          <br />
          <br />
          {this.renderTagTable(colWidth)}
        </CollapsibleSection>
      </div>
    );
  }

  genWidthStyle(width) {
    return {
      width: `${width}px`,
      minWidth: `${width}px`,
      maxWidth: `${width}px`,
    };
  }

  // eslint-disable-next-line no-unused-vars
  renderDataRows(
    list,
    colWidth,
    onlyShowDiff,
    highlightDiff = false,
    headerMap = (key, data) => key,
    formatter = (value) => value,
  ) {
    const keys = CompareRunUtil.getKeys(list);
    const data = {};
    const checkHasDiff = (values) => values.some((x) => x !== values[0]);
    keys.forEach((k) => (data[k] = { values: Array(list.length).fill(undefined) }));
    list.forEach((records, i) => {
      records.forEach((r) => (data[r.key].values[i] = r.value));
    });
    keys.forEach((k) => (data[k].hasDiff = checkHasDiff(data[k].values)));

    const colWidthStyle = this.genWidthStyle(colWidth);

    return keys
      .filter((k) => !onlyShowDiff || data[k].hasDiff)
      .map((k) => {
        const { values, hasDiff } = data[k];
        const rowClass = highlightDiff && hasDiff ? 'diff-row' : undefined;
        return (
          <tr key={k} className={rowClass}>
            <th scope='row' className='head-value sticky-header' css={colWidthStyle}>
              {headerMap(k, values)}
            </th>
            {values.map((value, i) => {
              const cellText = value === undefined ? '' : formatter(value);
              return (
                <td
                  className='data-value'
                  key={this.props.runInfos[i].run_uuid}
                  css={colWidthStyle}
                >
                  <Tooltip
                    title={cellText}
                    color='gray'
                    placement='topLeft'
                    overlayStyle={{ maxWidth: '400px' }}
                    mouseEnterDelay={1.0}
                  >
                    <span className='truncate-text single-line'>{cellText}</span>
                  </Tooltip>
                </td>
              );
            })}
          </tr>
        );
      });
  }
}

const mapStateToProps = (state, ownProps) => {
  const { comparedExperimentIds, hasComparedExperimentsBefore } = state.compareExperiments;
  const runInfos = [];
  const metricLists = [];
  const paramLists = [];
  const tagLists = [];
  const runNames = [];
  const runDisplayNames = [];
  const { experimentIds, runUuids } = ownProps;
  const experiments = experimentIds.map((experimentId) => getExperiment(experimentId, state));
  runUuids.forEach((runUuid) => {
    runInfos.push(getRunInfo(runUuid, state));
    metricLists.push(Object.values(getLatestMetrics(runUuid, state)));
    paramLists.push(Object.values(getParams(runUuid, state)));
    const runTags = getRunTags(runUuid, state);
    const visibleTags = Utils.getVisibleTagValues(runTags).map(([key, value]) => ({
      key,
      value,
    }));
    tagLists.push(visibleTags);
    runDisplayNames.push(Utils.getRunDisplayName(runTags, runUuid));
    runNames.push(Utils.getRunName(runTags));
  });
  return {
    experiments,
    runInfos,
    metricLists,
    paramLists,
    tagLists,
    runNames,
    runDisplayNames,
    comparedExperimentIds,
    hasComparedExperimentsBefore,
  };
};

export default withRouter(connect(mapStateToProps)(injectIntl(CompareRunView)));
