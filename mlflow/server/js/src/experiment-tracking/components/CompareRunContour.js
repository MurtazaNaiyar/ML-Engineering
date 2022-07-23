import React, { Component } from 'react';
import { AllHtmlEntities } from 'html-entities';
import { Switch, Row, Col, Select } from 'antd';
import PropTypes from 'prop-types';
import { getParams, getRunInfo } from '../reducers/Reducers';
import { connect } from 'react-redux';
import './CompareRunView.css';
import { RunInfo } from '../sdk/MlflowMessages';
import Utils from '../../common/utils/Utils';
import { getLatestMetrics } from '../reducers/MetricReducer';
import './CompareRunContour.css';
import CompareRunUtil from './CompareRunUtil';
import { FormattedMessage } from 'react-intl';
import { LazyPlot } from './LazyPlot';

const { Option, OptGroup } = Select;
export class CompareRunContour extends Component {
  static propTypes = {
    runInfos: PropTypes.arrayOf(PropTypes.instanceOf(RunInfo)).isRequired,
    metricLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    paramLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    runDisplayNames: PropTypes.arrayOf(PropTypes.string).isRequired,
  };

  // Size limits for displaying keys and values in our plot axes and tooltips
  static MAX_PLOT_KEY_LENGTH = 40;
  static MAX_PLOT_VALUE_LENGTH = 60;

  constructor(props) {
    super(props);

    this.entities = new AllHtmlEntities();

    this.metricKeys = CompareRunUtil.getKeys(this.props.metricLists, true);
    this.paramKeys = CompareRunUtil.getKeys(this.props.paramLists, true);

    if (this.paramKeys.length + this.metricKeys.length < 3) {
      this.state = { disabled: true };
    } else {
      const common = { disabled: false, reverseColor: false };
      if (this.metricKeys.length === 0) {
        this.state = {
          ...common,
          xaxis: { key: this.paramKeys[0], isMetric: false },
          yaxis: { key: this.paramKeys[1], isMetric: false },
          zaxis: { key: this.paramKeys[2], isMetric: false },
        };
      } else if (this.paramKeys.length === 0) {
        this.state = {
          ...common,
          xaxis: { key: this.metricKeys[0], isMetric: true },
          yaxis: { key: this.metricKeys[1], isMetric: true },
          zaxis: { key: this.metricKeys[2], isMetric: true },
        };
      } else if (this.paramKeys.length === 1) {
        this.state = {
          ...common,
          xaxis: { key: this.paramKeys[0], isMetric: false },
          yaxis: { key: this.metricKeys[0], isMetric: true },
          zaxis: { key: this.metricKeys[1], isMetric: true },
        };
      } else {
        this.state = {
          ...common,
          xaxis: { key: this.paramKeys[0], isMetric: false },
          yaxis: { key: this.paramKeys[1], isMetric: false },
          zaxis: { key: this.metricKeys[0], isMetric: true },
        };
      }
    }
  }

  /**
   * Get the value of the metric/param described by {key, isMetric}, in run i
   */
  getValue(i, { key, isMetric }) {
    const value = CompareRunUtil.findInList(
      (isMetric ? this.props.metricLists : this.props.paramLists)[i],
      key,
    );
    return value === undefined ? value : value.value;
  }

  /**
   * Encode HTML entities in a string (since Plotly's tooltips take HTML)
   */
  encodeHtml(str) {
    return this.entities.encode(str);
  }

  getColorscale() {
    /*
     * contour plot has an option named "reversescale" which
     * reverses the color mapping if True, but it doesn't work properly now.
     *
     * https://github.com/plotly/plotly.js/issues/4430
     *
     * This function is a temporary workaround for the issue.
     */
    const colorscale = [
      [0, 'rgb(5,10,172)'],
      [0.35, 'rgb(40,60,190)'],
      [0.5, 'rgb(70,100,245)'],
      [0.6, 'rgb(90,120,245)'],
      [0.7, 'rgb(106,137,247)'],
      [1, 'rgb(220,220,220)'],
    ];

    if (this.state.reverseColor) {
      return colorscale;
    } else {
      // reverse only RGB values
      return colorscale.map(([val], index) => [val, colorscale[colorscale.length - 1 - index][1]]);
    }
  }

  render() {
    if (this.state.disabled) {
      return (
        <div>
          <FormattedMessage
            defaultMessage='Contour plots can only be rendered when comparing a group of runs
              with three or more unique metrics or params. Log more metrics or params to your
              runs to visualize them using the contour plot.'
            description='Text explanation when contour plot is disabled in comparison pages
              in MLflow'
          />
        </div>
      );
    }

    const keyLength = CompareRunContour.MAX_PLOT_KEY_LENGTH;

    const xs = [];
    const ys = [];
    const zs = [];
    const tooltips = [];

    this.props.runInfos.forEach((_, index) => {
      const x = this.getValue(index, this.state.xaxis);
      const y = this.getValue(index, this.state.yaxis);
      const z = this.getValue(index, this.state.zaxis);
      if (x === undefined || y === undefined || z === undefined) {
        return;
      }
      xs.push(parseFloat(x));
      ys.push(parseFloat(y));
      zs.push(parseFloat(z));
      tooltips.push(this.getPlotlyTooltip(index));
    });

    const maybeRenderPlot = () => {
      const invalidAxes = [];
      if (new Set(xs).size < 2) {
        invalidAxes.push('X');
      }
      if (new Set(ys).size < 2) {
        invalidAxes.push('Y');
      }
      if (invalidAxes.length > 0) {
        const messageHead =
          invalidAxes.length > 1
            ? `The ${invalidAxes.join(' and ')} axes don't`
            : `The ${invalidAxes[0]} axis doesn't`;
        return <>{`${messageHead} have enough unique data points to render the contour plot.`}</>;
      }

      return (
        <LazyPlot
          data={[
            // contour plot
            {
              z: zs,
              x: xs,
              y: ys,
              type: 'contour',
              hoverinfo: 'none',
              colorscale: this.getColorscale(),
              connectgaps: true,
              contours: {
                coloring: 'heatmap',
              },
            },
            // scatter plot
            {
              x: xs,
              y: ys,
              text: tooltips,
              hoverinfo: 'text',
              type: 'scattergl',
              mode: 'markers',
              marker: {
                size: 10,
                color: 'rgba(200, 50, 100, .75)',
              },
            },
          ]}
          layout={{
            margin: {
              t: 30,
            },
            hovermode: 'closest',
            xaxis: {
              title: this.encodeHtml(Utils.truncateString(this.state['xaxis'].key, keyLength)),
              range: [Math.min(...xs), Math.max(...xs)],
            },
            yaxis: {
              title: this.encodeHtml(Utils.truncateString(this.state['yaxis'].key, keyLength)),
              range: [Math.min(...ys), Math.max(...ys)],
            },
          }}
          className={'scatter-plotly'}
          config={{
            responsive: true,
            displaylogo: false,
            scrollZoom: true,
            modeBarButtonsToRemove: [
              'sendDataToCloud',
              'select2d',
              'lasso2d',
              'resetScale2d',
              'hoverClosestCartesian',
              'hoverCompareCartesian',
            ],
          }}
          useResizeHandler
        />
      );
    };

    return (
      <div className='responsive-table-container'>
        <div className='container-fluid'>
          <Row>
            <Col span={6}>
              <div css={styles.group}>
                <label htmlFor='x-axis-selector'>
                  <FormattedMessage
                    defaultMessage='X-axis:'
                    description='Label text for x-axis in contour plot comparison in MLflow'
                  />
                </label>
                {this.renderSelect('xaxis')}
              </div>
              <div css={styles.group}>
                <label htmlFor='y-axis-selector'>
                  <FormattedMessage
                    defaultMessage='Y-axis:'
                    description='Label text for y-axis in contour plot comparison in MLflow'
                  />
                </label>
                {this.renderSelect('yaxis')}
              </div>
              <div css={styles.group}>
                <label htmlFor='z-axis-selector'>
                  <FormattedMessage
                    defaultMessage='Z-axis:'
                    description='Label text for z-axis in contour plot comparison in MLflow'
                  />
                </label>
                {this.renderSelect('zaxis')}
              </div>
              <div className='inline-control'>
                <div className='control-label'>
                  <FormattedMessage
                    defaultMessage='Reverse color:'
                    description='Label text for reverse color toggle in contour plot comparison
                      in MLflow'
                  />
                </div>
                <Switch
                  className='show-point-toggle'
                  checkedChildren={
                    <FormattedMessage
                      defaultMessage='On'
                      description='Checked toggle text for reverse color toggle in contour plot
                        comparison in MLflow'
                    />
                  }
                  unCheckedChildren={
                    <FormattedMessage
                      defaultMessage='Off'
                      description='Unchecked toggle text for reverse color toggle in contour plot
                        comparison in MLflow'
                    />
                  }
                  onChange={(checked) => this.setState({ reverseColor: checked })}
                />
              </div>
            </Col>
            <Col span={18}>{maybeRenderPlot()}</Col>
          </Row>
        </div>
      </div>
    );
  }

  renderSelect(axis) {
    return (
      <Select
        css={styles.select}
        id={axis + '-axis-selector'}
        aria-label={`${axis} axis`}
        onChange={(value) => {
          const [prefix, ...keyParts] = value.split('-');
          const key = keyParts.join('-');
          const isMetric = prefix === 'metric';
          this.setState({ [axis]: { isMetric, key } });
        }}
        value={(this.state[axis].isMetric ? 'metric-' : 'param-') + this.state[axis].key}
      >
        <OptGroup label='Parameter'>
          {this.paramKeys.map((p) => (
            <Option key={'param-' + p} value={'param-' + p}>
              {p}
            </Option>
          ))}
        </OptGroup>
        <OptGroup label='Metric'>
          {this.metricKeys.map((m) => (
            <Option key={'metric-' + m} value={'metric-' + m}>
              {m}
            </Option>
          ))}
        </OptGroup>
      </Select>
    );
  }

  getPlotlyTooltip(index) {
    const keyLength = CompareRunContour.MAX_PLOT_KEY_LENGTH;
    const valueLength = CompareRunContour.MAX_PLOT_VALUE_LENGTH;
    const runName = this.props.runDisplayNames[index];
    let result = `<b>${this.encodeHtml(runName)}</b><br>`;
    const paramList = this.props.paramLists[index];
    paramList.forEach((p) => {
      result +=
        this.encodeHtml(Utils.truncateString(p.key, keyLength)) +
        ': ' +
        this.encodeHtml(Utils.truncateString(p.value, valueLength)) +
        '<br>';
    });
    const metricList = this.props.metricLists[index];
    if (metricList.length > 0) {
      result += paramList.length > 0 ? '<br>' : '';
      metricList.forEach((m) => {
        result +=
          this.encodeHtml(Utils.truncateString(m.key, keyLength)) +
          ': ' +
          Utils.formatMetric(m.value) +
          '<br>';
      });
    }
    return result;
  }
}

const styles = {
  select: {
    width: '100%',
  },
  group: {
    marginBottom: 16,
  },
};

const mapStateToProps = (state, ownProps) => {
  const runInfos = [];
  const metricLists = [];
  const paramLists = [];
  const { runUuids } = ownProps;
  runUuids.forEach((runUuid) => {
    runInfos.push(getRunInfo(runUuid, state));
    metricLists.push(Object.values(getLatestMetrics(runUuid, state)));
    paramLists.push(Object.values(getParams(runUuid, state)));
  });
  return { runInfos, metricLists, paramLists };
};

export default connect(mapStateToProps)(CompareRunContour);
