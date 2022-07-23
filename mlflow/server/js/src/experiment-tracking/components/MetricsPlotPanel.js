import React from 'react';
import { connect } from 'react-redux';
import Utils from '../../common/utils/Utils';
import RequestStateWrapper from '../../common/components/RequestStateWrapper';
import { getMetricHistoryApi, getRunApi } from '../actions';
import PropTypes from 'prop-types';
import _ from 'lodash';
import { MetricsPlotView } from './MetricsPlotView';
import { getRunTags, getRunInfo } from '../reducers/Reducers';
import {
  MetricsPlotControls,
  X_AXIS_WALL,
  X_AXIS_RELATIVE,
  X_AXIS_STEP,
} from './MetricsPlotControls';
import MetricsSummaryTable from './MetricsSummaryTable';
import qs from 'qs';
import { withRouter } from 'react-router-dom';
import Routes from '../routes';
import { RunLinksPopover } from './RunLinksPopover';
import { getUUID } from '../../common/utils/ActionUtils';
import { saveAs } from 'file-saver';

export const CHART_TYPE_LINE = 'line';
export const CHART_TYPE_BAR = 'bar';

export const METRICS_PLOT_POLLING_INTERVAL_MS = 10 * 1000; // 10 seconds
// A run is considered as 'hanging' if its status is 'RUNNING' but its latest metric was logged
// prior to this threshold. The metrics plot doesn't automatically update hanging runs.
export const METRICS_PLOT_HANGING_RUN_THRESHOLD_MS = 3600 * 24 * 7 * 1000; // 1 week

export const convertMetricsToCsv = (metrics) => {
  const header = ['run_id', ...Object.keys(metrics[0].history[0])];
  const rows = metrics.flatMap(({ runUuid, history }) =>
    history.map((metric) => [runUuid, ...Object.values(metric)]),
  );
  return [header]
    .concat(rows)
    .map((row) => row.join(','))
    .join('\n');
};

export class MetricsPlotPanel extends React.Component {
  static propTypes = {
    experimentIds: PropTypes.arrayOf(PropTypes.string).isRequired,
    runUuids: PropTypes.arrayOf(PropTypes.string).isRequired,
    completedRunUuids: PropTypes.arrayOf(PropTypes.string).isRequired,
    metricKey: PropTypes.string.isRequired,
    // A map of { runUuid : { metricKey: value } }
    latestMetricsByRunUuid: PropTypes.object.isRequired,
    // An array of distinct metric keys across all runUuids
    distinctMetricKeys: PropTypes.arrayOf(PropTypes.string).isRequired,
    // An array of { metricKey, history, runUuid, runDisplayName }
    metricsWithRunInfoAndHistory: PropTypes.arrayOf(PropTypes.object).isRequired,
    getMetricHistoryApi: PropTypes.func.isRequired,
    getRunApi: PropTypes.func.isRequired,
    location: PropTypes.object.isRequired,
    history: PropTypes.object.isRequired,
    runDisplayNames: PropTypes.arrayOf(PropTypes.string).isRequired,
  };

  // The fields below are exposed as instance attributes rather than component state so that they
  // can be updated without triggering a rerender.
  //
  // ID of Javascript future (created via setTimeout()) used to trigger legend-click events after a
  // delay, to allow time for double-click events to occur
  legendClickTimeout = null;
  // Time (millis after Unix epoch) since last legend click - if two clicks occur in short
  // succession, we trigger a double-click event & cancel the pending single-click.
  prevLegendClickTime = Math.inf;

  // Last curve ID clicked in the legend, used to determine if we're double-clicking on a specific
  // legend curve
  lastClickedLegendCurveId = null;

  // Max time interval (in milliseconds) between two successive clicks on the metric plot legend
  // that constitutes a double-click
  MAX_DOUBLE_CLICK_INTERVAL_MS = 300;

  // Delay (in ms) between when a user clicks on the metric plot legend & when event-handler logic
  // (to toggle display of the selected curve on or off) actually fires. Set to a larger value than
  // MAX_DOUBLE_CLICK_INTERVAL_MS to allow time for the double-click handler to fire before firing
  // a single-click event.
  SINGLE_CLICK_EVENT_DELAY_MS = this.MAX_DOUBLE_CLICK_INTERVAL_MS + 10;

  constructor(props) {
    super(props);
    this.state = {
      historyRequestIds: [],
      popoverVisible: false,
      popoverX: 0,
      popoverY: 0,
      popoverRunItems: [],
      focused: true,
    };
    this.displayPopover = false;
    this.intervalId = null;
    this.loadMetricHistory(this.props.runUuids, this.getUrlState().selectedMetricKeys);
  }

  hasMultipleExperiments() {
    return this.props.experimentIds && this.props.experimentIds.length > 1;
  }

  onFocus = () => {
    this.setState({ focused: true });
  };

  onBlur = () => {
    this.setState({ focused: false });
  };

  clearEventListeners = () => {
    // `window.removeEventListener` does nothing when called with an unregistered event listener:
    // https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/removeEventListener
    window.removeEventListener('focus', this.onFocus);
    window.removeEventListener('blur', this.onBlur);
  };

  clearInterval = () => {
    // `clearInterval` does nothing when called with `null` or `undefine`:
    // https://www.w3.org/TR/2011/WD-html5-20110525/timers.html#dom-windowtimers-cleartimeout
    clearInterval(this.intervalId);
    this.intervalId = null;
  };

  allRunsCompleted = () => {
    return this.props.completedRunUuids.length === this.props.runUuids.length;
  };

  isHangingRunUuid = (activeRunUuid) => {
    const metrics = this.props.latestMetricsByRunUuid[activeRunUuid];
    if (!metrics) {
      return false;
    }
    const timestamps = Object.values(metrics).map(({ timestamp }) => timestamp);
    const latestTimestamp = Math.max(...timestamps);
    return new Date().getTime() - latestTimestamp > METRICS_PLOT_HANGING_RUN_THRESHOLD_MS;
  };

  getActiveRunUuids = () => {
    const { completedRunUuids, runUuids } = this.props;
    const activeRunUuids = _.difference(runUuids, completedRunUuids);
    return activeRunUuids.filter(_.negate(this.isHangingRunUuid)); // Exclude hanging runs
  };

  shouldPoll = () => {
    return !(this.allRunsCompleted() || this.getActiveRunUuids().length === 0);
  };

  componentDidMount() {
    if (this.shouldPoll()) {
      // Set event listeners to detect when this component gains/loses focus,
      // e.g., a user switches to a different browser tab or app.
      window.addEventListener('blur', this.onBlur);
      window.addEventListener('focus', this.onFocus);
      this.intervalId = setInterval(() => {
        // Skip polling if this component is out of focus.
        if (this.state.focused) {
          const activeRunUuids = this.getActiveRunUuids();
          this.loadMetricHistory(activeRunUuids, this.getUrlState().selectedMetricKeys);
          this.loadRuns(activeRunUuids);

          if (!this.shouldPoll()) {
            this.clearEventListeners();
            this.clearInterval();
          }
        }
      }, METRICS_PLOT_POLLING_INTERVAL_MS);
    }
  }

  componentWillUnmount() {
    this.clearEventListeners();
    this.clearInterval();
  }

  getUrlState() {
    return Utils.getMetricPlotStateFromUrl(this.props.location.search);
  }

  static predictChartType(metrics) {
    // Show bar chart when every metric has exactly 1 metric history
    if (
      metrics &&
      metrics.length &&
      _.every(metrics, (metric) => metric.history && metric.history.length === 1)
    ) {
      return CHART_TYPE_BAR;
    }
    return CHART_TYPE_LINE;
  }

  static isComparing(search) {
    const params = qs.parse(search);
    const runs = params && params['?runs'];
    return runs ? JSON.parse(runs).length > 1 : false;
  }

  // Update page URL from component state. Intended to be called after React applies component
  // state updates, e.g. in a setState callback
  updateUrlState = (updatedState) => {
    const { runUuids, metricKey, location, history } = this.props;
    const experimentIds = JSON.parse(qs.parse(location.search)['experiments']);
    const newState = {
      ...this.getUrlState(),
      ...updatedState,
    };
    const {
      selectedXAxis,
      selectedMetricKeys,
      showPoint,
      yAxisLogScale,
      lineSmoothness,
      layout,
      deselectedCurves,
      lastLinearYAxisRange,
    } = newState;
    history.replace(
      Routes.getMetricPageRoute(
        runUuids,
        metricKey,
        experimentIds,
        selectedMetricKeys,
        layout,
        selectedXAxis,
        yAxisLogScale,
        lineSmoothness,
        showPoint,
        deselectedCurves,
        lastLinearYAxisRange,
      ),
    );
  };

  loadMetricHistory = (runUuids, metricKeys) => {
    const requestIds = [];
    const { latestMetricsByRunUuid } = this.props;
    runUuids.forEach((runUuid) => {
      metricKeys.forEach((metricKey) => {
        if (latestMetricsByRunUuid[runUuid][metricKey]) {
          const id = getUUID();
          this.props.getMetricHistoryApi(runUuid, metricKey, id);
          requestIds.push(id);
        }
      });
    });
    return requestIds;
  };

  loadRuns = (runUuids) => {
    const requestIds = [];
    runUuids.forEach((runUuid) => {
      const id = getUUID();
      this.props.getRunApi(runUuid);
      requestIds.push(id);
    });
    return requestIds;
  };

  getMetrics = () => {
    /* eslint-disable no-param-reassign */
    const state = this.getUrlState();
    const selectedMetricsSet = new Set(state.selectedMetricKeys);
    const { selectedXAxis } = state;
    const { metricsWithRunInfoAndHistory } = this.props;

    // Take only selected metrics
    const metrics = metricsWithRunInfoAndHistory.filter((m) => selectedMetricsSet.has(m.metricKey));

    // Sort metric history based on selected x-axis
    metrics.forEach((metric) => {
      const isStep =
        selectedXAxis === X_AXIS_STEP && metric.history[0] && _.isNumber(metric.history[0].step);
      // Metric history can be large. Doing an in-place here to save memory
      metric.history.sort(isStep ? Utils.compareByStepAndTimestamp : Utils.compareByTimestamp);
    });
    return metrics;
  };

  /**
   * Handle changes in the scale type of the y-axis
   * @param yAxisLogScale: Boolean - if true, y-axis should be converted to log scale, and if false,
   * y-axis scale should be converted to a linear scale.
   */
  handleYAxisLogScaleChange = (yAxisLogScale) => {
    const state = this.getUrlState();
    const newLayout = _.cloneDeep(state.layout);
    const newAxisType = yAxisLogScale ? 'log' : 'linear';

    // Handle special case of a linear y-axis scale with negative values converted to log scale &
    // now being restored to linear scale, by restoring the old linear-axis range from
    // state.linearYAxisRange. In particular, we assume that if state.linearYAxisRange
    // is non-empty, it contains a linear y axis range with negative values.
    if (!yAxisLogScale && state.lastLinearYAxisRange && state.lastLinearYAxisRange.length > 0) {
      newLayout.yaxis = {
        type: 'linear',
        range: state.lastLinearYAxisRange,
      };
      this.updateUrlState({ layout: newLayout, lastLinearYAxisRange: [] });
      return;
    }

    // Otherwise, if plot previously had no y axis range configured, simply set the axis type to
    // log or linear scale appropriately
    if (!state.layout.yaxis || !state.layout.yaxis.range) {
      newLayout.yaxis = {
        type: newAxisType,
        autorange: true,
        ...(newAxisType === 'log' ? { exponentformat: 'e' } : {}),
      };
      this.updateUrlState({ layout: newLayout, lastLinearYAxisRange: [] });
      return;
    }

    // lastLinearYAxisRange contains the last range used for a linear-scale y-axis. We set
    // this state attribute if and only if we're converting from a linear-scale y-axis with
    // negative bounds to a log scale axis, so that we can restore the negative bounds if we
    // subsequently convert back to a linear scale axis. Otherwise, we reset this attribute to an
    // empty array
    let lastLinearYAxisRange = [];

    // At this point, we know the plot previously had a y axis specified with range bounds
    // Convert the range to/from log scale as appropriate
    const oldLayout = state.layout;
    const oldYRange = oldLayout.yaxis.range;
    if (yAxisLogScale) {
      if (oldYRange[0] <= 0) {
        lastLinearYAxisRange = oldYRange;
        // When converting to log scale, handle negative values (which have no log-scale
        // representation as taking the log of a negative number is not possible) as follows:
        // If bottom of old Y range is negative, then tell plotly to infer the log y-axis scale
        // (set 'autorange' to true), and preserve the old range in the lastLinearYAxisRange
        // state attribute so that we can restore it if the user converts back to a linear-scale
        // y axis. We defer to Plotly's autorange here under the assumption that it will produce
        // a reasonable y-axis log scale for plots containing negative values.
        newLayout.yaxis = {
          type: 'log',
          autorange: true,
          exponentformat: 'e',
        };
      } else {
        newLayout.yaxis = {
          type: 'log',
          range: [Math.log(oldYRange[0]) / Math.log(10), Math.log(oldYRange[1]) / Math.log(10)],
          exponentformat: 'e',
        };
      }
    } else {
      // Otherwise, convert from log to linear scale normally
      newLayout.yaxis = {
        type: 'linear',
        range: [Math.pow(10, oldYRange[0]), Math.pow(10, oldYRange[1])],
      };
    }
    this.updateUrlState({ layout: newLayout, lastLinearYAxisRange });
  };

  /**
   * Handle changes in the type of the metric plot's X axis (e.g. changes from wall-clock
   * scale to relative-time scale to step-based scale).
   * @param e: Selection event such that e.target.value is a string containing the new X axis type
   */
  handleXAxisChange = (e) => {
    // Set axis value type, & reset axis scaling via autorange
    const state = this.getUrlState();
    const axisEnumToPlotlyType = {
      [X_AXIS_WALL]: 'date',
      [X_AXIS_RELATIVE]: 'linear',
      [X_AXIS_STEP]: 'linear',
    };
    const axisType = axisEnumToPlotlyType[e.target.value] || 'linear';
    const newLayout = {
      ...state.layout,
      xaxis: {
        autorange: true,
        type: axisType,
      },
    };
    this.updateUrlState({ selectedXAxis: e.target.value, layout: newLayout });
  };

  getAxisType() {
    const state = this.getUrlState();
    return state.layout && state.layout.yaxis && state.layout.yaxis.type === 'log'
      ? 'log'
      : 'linear';
  }

  /**
   * Handle changes to metric plot layout (x & y axis ranges), e.g. specifically if the user
   * zooms in or out on the plot.
   *
   * @param newLayout: Object containing the new Plot layout. See
   * https://plot.ly/javascript/plotlyjs-events/#update-data for details on the object's fields
   * and schema.
   */
  handleLayoutChange = (newLayout) => {
    this.displayPopover = false;
    const state = this.getUrlState();
    // Unfortunately, we need to parse out the x & y axis range changes from the onLayout event...
    // see https://plot.ly/javascript/plotlyjs-events/#update-data
    const {
      'xaxis.range[0]': newXRange0,
      'xaxis.range[1]': newXRange1,
      'yaxis.range[0]': newYRange0,
      'yaxis.range[1]': newYRange1,
      'xaxis.autorange': xAxisAutorange,
      'yaxis.autorange': yAxisAutorange,
      'yaxis.showspikes': yAxisShowSpikes,
      'xaxis.showspikes': xAxisShowSpikes,
      ...restFields
    } = newLayout;

    let mergedLayout = {
      ...state.layout,
      ...restFields,
    };
    let lastLinearYAxisRange = [...state.lastLinearYAxisRange];

    // Set fields for x axis
    const newXAxis = mergedLayout.xaxis || {};
    if (newXRange0 !== undefined && newXRange1 !== undefined) {
      newXAxis.range = [newXRange0, newXRange1];
      newXAxis.autorange = false;
    }
    if (xAxisShowSpikes) {
      newXAxis.showspikes = true;
    }
    if (xAxisAutorange) {
      newXAxis.autorange = true;
    }
    // Set fields for y axis
    const newYAxis = mergedLayout.yaxis || {};
    if (newYRange0 !== undefined && newYRange1 !== undefined) {
      newYAxis.range = [newYRange0, newYRange1];
      newYAxis.autorange = false;
    }
    if (yAxisShowSpikes) {
      newYAxis.showspikes = true;
    }
    if (yAxisAutorange) {
      lastLinearYAxisRange = [];
      const axisType =
        state.layout && state.layout.yaxis && state.layout.yaxis.type === 'log' ? 'log' : 'linear';
      newYAxis.autorange = true;
      newYAxis.type = axisType;
    }
    if (newYAxis.type === 'log') {
      newYAxis.exponentformat = 'e';
    }
    // Merge new X & Y axis info into layout
    mergedLayout = {
      ...mergedLayout,
      xaxis: newXAxis,
      yaxis: newYAxis,
    };
    this.updateUrlState({ layout: mergedLayout, lastLinearYAxisRange });
  };

  handleDownloadCsv = () => {
    const csv = convertMetricsToCsv(this.props.metricsWithRunInfoAndHistory);
    const blob = new Blob([csv], { type: 'application/csv;charset=utf-8' });
    saveAs(blob, 'metrics.csv');
  };

  // Return unique key identifying the curve or bar chart corresponding to the specified
  // Plotly plot data element
  static getCurveKey(plotDataElem) {
    // In bar charts, each legend item consists of a single run ID (all bars for that run are
    // associated with & toggled by that legend item)
    if (plotDataElem.type === 'bar') {
      return plotDataElem.runId;
    } else {
      // In line charts, each (run, metricKey) tuple has its own legend item, so construct
      // a unique legend item identifier by concatenating the run id & metric key
      return Utils.getCurveKey(plotDataElem.runId, plotDataElem.metricName);
    }
  }

  /**
   * Handle clicking on a single curve within the plot legend in order to toggle its display
   * on/off.
   */
  handleLegendClick = ({ curveNumber, data }) => {
    // If two clicks in short succession, trigger double-click event
    const state = this.getUrlState();
    const currentTime = Date.now();
    if (
      currentTime - this.prevLegendClickTime < this.MAX_DOUBLE_CLICK_INTERVAL_MS &&
      curveNumber === this.lastClickedLegendCurveId
    ) {
      this.handleLegendDoubleClick({ curveNumber, data });
      this.prevLegendClickTime = Math.inf;
    } else {
      // Otherwise, record time of current click & trigger click event
      // Wait full double-click window to trigger setting state, and only if there was no
      // double-click do we run the single-click logic (we wait a little extra to be safe)
      const curveKey = MetricsPlotPanel.getCurveKey(data[curveNumber]);
      this.legendClickTimeout = window.setTimeout(() => {
        const existingDeselectedCurves = new Set(state.deselectedCurves);
        if (existingDeselectedCurves.has(curveKey)) {
          existingDeselectedCurves.delete(curveKey);
        } else {
          existingDeselectedCurves.add(curveKey);
        }
        this.updateUrlState({ deselectedCurves: Array.from(existingDeselectedCurves) });
      }, this.SINGLE_CLICK_EVENT_DELAY_MS);
      this.prevLegendClickTime = currentTime;
    }
    this.lastClickedLegendCurveId = curveNumber;
    // Return false to disable plotly event handler
    return false;
  };

  /**
   * Handle double-clicking on a single curve within the plot legend in order to toggle display
   * of the selected curve on (and disable display of all other curves).
   */
  handleLegendDoubleClick = ({ curveNumber, data }) => {
    window.clearTimeout(this.legendClickTimeout);
    // Exclude everything besides the current curve key
    const curveKey = MetricsPlotPanel.getCurveKey(data[curveNumber]);
    const allCurveKeys = data.map((elem) => MetricsPlotPanel.getCurveKey(elem));
    const newDeselectedCurves = allCurveKeys.filter((curvePair) => curvePair !== curveKey);
    this.updateUrlState({ deselectedCurves: newDeselectedCurves });
    return false;
  };

  handleMetricsSelectChange = (metricKeys) => {
    const existingMetricKeys = this.getUrlState().selectedMetricKeys || [];
    const newMetricKeys = metricKeys.filter((k) => !existingMetricKeys.includes(k));

    const requestIds = this.loadMetricHistory(this.props.runUuids, newMetricKeys);
    this.setState(
      (prevState) => ({
        historyRequestIds: [...prevState.historyRequestIds, ...requestIds],
      }),
      () => {
        this.updateUrlState({
          selectedMetricKeys: metricKeys,
        });
      },
    );
  };

  handleShowPointChange = (showPoint) => this.updateUrlState({ showPoint });

  handleLineSmoothChange = (lineSmoothness) => this.updateUrlState({ lineSmoothness });

  handleKeyDownOnPopover = ({ key }) => {
    if (key === 'Escape') {
      this.setState({ popoverVisible: false });
    }
  };

  updatePopover = (data) => {
    this.displayPopover = !this.displayPopover;

    // Ignore double click.
    setTimeout(() => {
      if (this.displayPopover) {
        this.displayPopover = false;
        const { popoverVisible, popoverX, popoverY } = this.state;
        const {
          points,
          event: { clientX, clientY },
        } = data;
        const samePointClicked = popoverX === clientX && popoverY === clientY;
        const runItems = points
          .sort((a, b) => b.y - a.y)
          .map((point) => ({
            runId: point.data.runId,
            name: point.data.name,
            color: point.fullData.marker.color,
            y: point.y,
          }));

        this.setState({
          popoverVisible: !popoverVisible || !samePointClicked,
          popoverX: clientX,
          popoverY: clientY,
          popoverRunItems: runItems,
        });
      }
    }, 300);
  };

  render() {
    const { experimentIds, runUuids, runDisplayNames, distinctMetricKeys, location } = this.props;
    const { popoverVisible, popoverX, popoverY, popoverRunItems } = this.state;
    const state = this.getUrlState();
    const { showPoint, selectedXAxis, selectedMetricKeys, lineSmoothness } = state;
    const yAxisLogScale = this.getAxisType() === 'log';
    const { historyRequestIds } = this.state;
    const metrics = this.getMetrics();
    const chartType = MetricsPlotPanel.predictChartType(metrics);
    return (
      <div className='metrics-plot-container'>
        <MetricsPlotControls
          numRuns={this.props.runUuids.length}
          numCompletedRuns={this.props.completedRunUuids.length}
          distinctMetricKeys={distinctMetricKeys}
          selectedXAxis={selectedXAxis}
          selectedMetricKeys={selectedMetricKeys}
          handleXAxisChange={this.handleXAxisChange}
          handleMetricsSelectChange={this.handleMetricsSelectChange}
          handleShowPointChange={this.handleShowPointChange}
          handleYAxisLogScaleChange={this.handleYAxisLogScaleChange}
          handleLineSmoothChange={this.handleLineSmoothChange}
          chartType={chartType}
          initialLineSmoothness={lineSmoothness}
          yAxisLogScale={yAxisLogScale}
          showPoint={showPoint}
          handleDownloadCsv={this.handleDownloadCsv}
        />
        <div className='metrics-plot-data'>
          <RequestStateWrapper
            requestIds={historyRequestIds}
            // In this case where there are no history request IDs (e.g. on the
            // initial page load / before we try to load additional metrics),
            // optimistically render the children
            shouldOptimisticallyRender={historyRequestIds.length === 0}
          >
            {this.hasMultipleExperiments() ? null : (
              <RunLinksPopover
                experimentId={experimentIds[0]}
                visible={popoverVisible}
                x={popoverX}
                y={popoverY}
                runItems={popoverRunItems}
                handleKeyDown={this.handleKeyDownOnPopover}
                handleClose={() => this.setState({ popoverVisible: false })}
                handleVisibleChange={(visible) => this.setState({ popoverVisible: visible })}
              />
            )}
            <MetricsPlotView
              runUuids={runUuids}
              runDisplayNames={runDisplayNames}
              xAxis={selectedXAxis}
              metrics={this.getMetrics()}
              metricKeys={selectedMetricKeys}
              showPoint={showPoint}
              chartType={chartType}
              isComparing={MetricsPlotPanel.isComparing(location.search)}
              lineSmoothness={lineSmoothness}
              extraLayout={state.layout}
              deselectedCurves={state.deselectedCurves}
              onLayoutChange={this.handleLayoutChange}
              onClick={this.updatePopover}
              onLegendClick={this.handleLegendClick}
              onLegendDoubleClick={this.handleLegendDoubleClick}
            />
            <MetricsSummaryTable
              runUuids={runUuids}
              runDisplayNames={runDisplayNames}
              metricKeys={selectedMetricKeys}
            />
          </RequestStateWrapper>
        </div>
      </div>
    );
  }
}

const mapStateToProps = (state, ownProps) => {
  const { runUuids } = ownProps;
  const completedRunUuids = runUuids.filter(
    (runUuid) => getRunInfo(runUuid, state).status !== 'RUNNING',
  );
  const { latestMetricsByRunUuid, metricsByRunUuid } = state.entities;

  // All metric keys from all runUuids, non-distinct
  const metricKeys = _.flatMap(runUuids, (runUuid) => {
    const latestMetrics = latestMetricsByRunUuid[runUuid];
    return latestMetrics ? Object.keys(latestMetrics) : [];
  });
  const distinctMetricKeys = [...new Set(metricKeys)].sort();
  const runDisplayNames = [];

  // Flat array of all metrics, with history and information of the run it belongs to
  // This is used for underlying MetricsPlotView & predicting chartType for MetricsPlotControls
  const metricsWithRunInfoAndHistory = _.flatMap(runUuids, (runUuid) => {
    const runDisplayName = Utils.getRunDisplayName(getRunTags(runUuid, state), runUuid);
    runDisplayNames.push(runDisplayName);
    const metricsHistory = metricsByRunUuid[runUuid];
    return metricsHistory
      ? Object.keys(metricsHistory).map((metricKey) => {
          const history = metricsHistory[metricKey].map((entry) => ({
            key: entry.key,
            value: entry.value,
            step: Number.parseInt(entry.step, 10) || 0, // default step to 0
            timestamp: Number.parseFloat(entry.timestamp),
          }));
          return { metricKey, history, runUuid, runDisplayName };
        })
      : [];
  });

  return {
    runDisplayNames,
    latestMetricsByRunUuid,
    distinctMetricKeys,
    metricsWithRunInfoAndHistory,
    completedRunUuids,
  };
};

const mapDispatchToProps = { getMetricHistoryApi, getRunApi };

export default withRouter(connect(mapStateToProps, mapDispatchToProps)(MetricsPlotPanel));
