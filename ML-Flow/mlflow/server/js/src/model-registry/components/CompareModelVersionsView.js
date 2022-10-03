import React, { Component } from 'react';
import PropTypes from 'prop-types';
import { connect } from 'react-redux';
import { Link } from 'react-router-dom';
import _ from 'lodash';
import { FormattedMessage } from 'react-intl';
import { Switch } from 'antd';
import { Tabs, useDesignSystemTheme } from '@databricks/design-system';

import { getParams, getRunInfo, getRunTags } from '../../experiment-tracking/reducers/Reducers';
import '../../experiment-tracking/components/CompareRunView.css';
import { RunInfo } from '../../experiment-tracking/sdk/MlflowMessages';
import { CompareRunScatter } from '../../experiment-tracking/components/CompareRunScatter';
import CompareRunContour from '../../experiment-tracking/components/CompareRunContour';
import Routes from '../../experiment-tracking/routes';
import { getLatestMetrics } from '../../experiment-tracking/reducers/MetricReducer';
import CompareRunUtil from '../../experiment-tracking/components/CompareRunUtil';
import Utils from '../../common/utils/Utils';
import ParallelCoordinatesPlotPanel from '../../experiment-tracking/components/ParallelCoordinatesPlotPanel';
import { modelListPageRoute, getModelPageRoute, getModelVersionPageRoute } from '../routes';
import { getModelVersionSchemas } from '../reducers';
import { PageHeader } from '../../shared/building_blocks/PageHeader';

const { TabPane } = Tabs;

function CenteredText(props) {
  const { theme } = useDesignSystemTheme();
  return (
    <div
      css={{
        textAlign: 'center',
        color: theme.colors.textSecondary,
      }}
      {...props}
    />
  );
}

function CompareTable(props) {
  const { theme } = useDesignSystemTheme();
  return (
    <table
      className='compare-table table'
      css={{
        'th.main-table-header': {
          backgroundColor: theme.colors.white,
          padding: 0,
        },
        'td.highlight-data': {
          backgroundColor: theme.colors.backgroundValidationWarning,
        },
      }}
      {...props}
    />
  );
}

function CollapseButton(props) {
  const { theme } = useDesignSystemTheme();
  return (
    <button
      css={{
        textAlign: 'left',
        display: 'flex',
        alignItems: 'center',
        border: 'none',
        backgroundColor: theme.colors.white,
        paddingLeft: 0,
        cursor: 'pointer',
      }}
      {...props}
    />
  );
}

export class CompareModelVersionsViewImpl extends Component {
  static propTypes = {
    runInfos: PropTypes.arrayOf(PropTypes.instanceOf(RunInfo)).isRequired,
    // Array that contains whether or not corresponding runInfo is valid.
    runInfosValid: PropTypes.arrayOf(PropTypes.bool).isRequired,
    runUuids: PropTypes.arrayOf(PropTypes.string).isRequired,
    metricLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    paramLists: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.object)).isRequired,
    // Array of user-specified run names. Elements may be falsy (e.g. empty string or undefined) if
    // a run was never given a name.
    runNames: PropTypes.arrayOf(PropTypes.string).isRequired,
    // Array of names to use when displaying runs. No element in this array should be falsy;
    // we expect this array to contain user-specified run names, or default display names
    // ("Run <uuid>") for runs without names.
    runDisplayNames: PropTypes.arrayOf(PropTypes.string).isRequired,
    modelName: PropTypes.string.isRequired,
    versionsToRuns: PropTypes.object.isRequired,
    inputsListByName: PropTypes.arrayOf(Array).isRequired,
    inputsListByIndex: PropTypes.arrayOf(Array).isRequired,
    outputsListByName: PropTypes.arrayOf(Array).isRequired,
    outputsListByIndex: PropTypes.arrayOf(Array).isRequired,
  };

  state = {
    inputActive: true,
    outputActive: true,
    paramsToggle: true,
    paramsActive: true,
    schemaToggle: true,
    compareByColumnNameToggle: false,
    schemaActive: true,
    metricToggle: true,
    metricActive: true,
  };

  icons = {
    plusIcon: <i className='far fa-plus-square-o' />,
    minusIcon: <i className='far fa-minus-square-o' />,
    downIcon: <i className='fas fa-caret-down' />,
    rightIcon: <i className='fas fa-caret-right' />,
    chartIcon: <i className='fas fa-line-chart padding-left-text' />,
  };

  onToggleClick = (active) => {
    this.setState((state) => ({
      [active]: !state[active],
    }));
  };

  render() {
    const {
      inputsListByIndex,
      inputsListByName,
      modelName,
      outputsListByIndex,
      outputsListByName,
      runInfos,
      runUuids,
      runDisplayNames,
    } = this.props;
    const title = (
      <FormattedMessage
        defaultMessage='Comparing {numVersions} Versions'
        description='Text for main title for the model comparison page'
        values={{ numVersions: this.props.runInfos.length }}
      />
    );
    const breadcrumbs = [
      <Link to={modelListPageRoute}>
        <FormattedMessage
          defaultMessage='Registered Models'
          description='Text for registered model link in the title for model comparison page'
        />
      </Link>,
      <Link to={getModelPageRoute(modelName)}>{modelName}</Link>,
      title,
    ];

    return (
      <div
        className='CompareModelVersionsView'
        css={{
          ...styles.compareModelVersionsView,
          ...styles.wrapper(runInfos.length),
        }}
      >
        <PageHeader title={title} breadcrumbs={breadcrumbs} />
        <div className='responsive-table-container'>
          <CompareTable>
            {this.renderTableHeader()}
            {this.renderModelVersionInfo()}
            {this.renderSectionHeader(
              'paramsActive',
              'paramsToggle',
              <FormattedMessage
                defaultMessage='Parameters'
                description='Table title text for parameters table in the model comparison page'
              />,
            )}
            {this.renderParams()}
            {this.renderSectionHeader(
              'schemaActive',
              'schemaToggle',
              <FormattedMessage
                defaultMessage='Schema'
                description='Table title text for schema table in the model comparison page'
              />,
              false,
              <Switch
                size='small'
                className='toggle-switch'
                style={{ marginLeft: 'auto' }}
                onChange={() => this.onToggleClick('compareByColumnNameToggle')}
              />,
              <div className='padding-left-text padding-right-text'>
                <span>
                  <FormattedMessage
                    defaultMessage='Ignore column ordering'
                    description='Toggle text that determines whether to ignore column order in the
                      model comparison page'
                  />
                </span>
              </div>,
            )}
            {this.renderSchemaSectionHeader(
              'inputActive',
              <FormattedMessage
                defaultMessage='Inputs'
                description='Table subtitle for schema inputs in the model comparison page'
              />,
            )}
            {this.renderSchema(
              'inputActive',
              <FormattedMessage
                defaultMessage='Inputs'
                description='Table section name for schema inputs in the model comparison page'
              />,
              inputsListByIndex,
              inputsListByName,
            )}
            {this.renderSchemaSectionHeader(
              'outputActive',
              <FormattedMessage
                defaultMessage='Outputs'
                description='Table subtitle for schema outputs in the model comparison page'
              />,
            )}
            {this.renderSchema(
              'outputActive',
              <FormattedMessage
                defaultMessage='Outputs'
                description='Table section name for schema outputs in the model comparison page'
              />,
              outputsListByIndex,
              outputsListByName,
            )}
            {this.renderSectionHeader(
              'metricActive',
              'metricToggle',
              <FormattedMessage
                defaultMessage='Metrics'
                description='Table title text for metrics table in the model comparison page'
              />,
            )}
            {this.renderMetrics()}
          </CompareTable>
        </div>
        <Tabs>
          <TabPane
            tab={
              <FormattedMessage
                defaultMessage='Scatter Plot'
                description='Tab text for scatter plot on the model comparison page'
              />
            }
            key='1'
          >
            <CompareRunScatter runUuids={runUuids} runDisplayNames={runDisplayNames} />
          </TabPane>
          <TabPane
            tab={
              <FormattedMessage
                defaultMessage='Contour Plot'
                description='Tab text for contour plot on the model comparison page'
              />
            }
            key='2'
          >
            <CompareRunContour runUuids={runUuids} runDisplayNames={runDisplayNames} />
          </TabPane>
          <TabPane
            tab={
              <FormattedMessage
                defaultMessage='Parallel Coordinates Plot'
                description='Tab text for parallel coordinates plot on the model comparison page'
              />
            }
            key='3'
          >
            <ParallelCoordinatesPlotPanel runUuids={runUuids} />
          </TabPane>
        </Tabs>
      </div>
    );
  }

  renderTableHeader() {
    const { runInfos, runInfosValid } = this.props;
    return (
      <thead>
        <tr className='table-row'>
          <th scope='row' className='row-header block-content'>
            <FormattedMessage
              defaultMessage='Run ID:'
              description='Text for run ID header in the main table in the model comparison page'
            />
          </th>
          {runInfos.map((r, idx) => (
            <th scope='column' className='data-value block-content' key={r.getRunUuid()}>
              {/* Do not show links for invalid run IDs */}
              {runInfosValid[idx] ? (
                <Link to={Routes.getRunPageRoute(r.getExperimentId(), r.getRunUuid())}>
                  {r.getRunUuid()}
                </Link>
              ) : (
                r.getRunUuid()
              )}
            </th>
          ))}
        </tr>
      </thead>
    );
  }

  renderModelVersionInfo() {
    const { runInfos, runInfosValid, versionsToRuns, runNames, modelName } = this.props;
    return (
      <tbody className='scrollable-table'>
        <tr className='table-row'>
          <th scope='row' className='data-value block-content'>
            <FormattedMessage
              defaultMessage='Model Version:'
              description='Text for model version row header in the main table in the model
                comparison page'
            />
          </th>
          {Object.keys(versionsToRuns).map((modelVersion) => {
            const run = versionsToRuns[modelVersion];
            return (
              <td className='meta-info block-content' key={run}>
                <Link to={getModelVersionPageRoute(modelName, modelVersion)}>{modelVersion}</Link>
              </td>
            );
          })}
        </tr>
        <tr className='table-row'>
          <th scope='row' className='data-value block-content'>
            <FormattedMessage
              defaultMessage='Run Name:'
              description='Text for run name row header in the main table in the model comparison
                page'
            />
          </th>
          {runNames.map((runName, i) => {
            return (
              <td className='meta-info block-content' key={runInfos[i].getRunUuid()}>
                <div className='truncate-text single-line cell-content'>{runName}</div>
              </td>
            );
          })}
        </tr>
        <tr className='table-row'>
          <th scope='row' className='data-value block-content'>
            <FormattedMessage
              defaultMessage='Start Time:'
              description='Text for start time row header in the main table in the model comparison
                page'
            />
          </th>
          {runInfos.map((run, idx) => {
            /* Do not attempt to get timestamps for invalid run IDs */
            const startTime =
              run.getStartTime() && runInfosValid[idx]
                ? Utils.formatTimestamp(run.getStartTime())
                : '(unknown)';
            return (
              <td className='meta-info block-content' key={run.getRunUuid()}>
                {startTime}
              </td>
            );
          })}
        </tr>
      </tbody>
    );
  }

  /* additional Switch and Text are antd Switch component and the text followed by the toggle switch
  this is currently used in schema section where we have an additional switch toggle for
  ignore column ordering, same logic can be applied if future section needs additional toggle */
  renderSectionHeader(
    activeSection,
    toggleSection,
    sectionName,
    leftToggle = true,
    additionalSwitch = null,
    additionalSwitchText = null,
  ) {
    const { runInfos } = this.props;
    const isActive = this.state[activeSection];
    const { downIcon, rightIcon } = this.icons;
    return (
      <tbody>
        <tr>
          <th
            scope='rowgroup'
            className='block-content main-table-header'
            colSpan={runInfos.length + 1}
          >
            <div className='switch-button-container'>
              <CollapseButton onClick={() => this.onToggleClick(activeSection)}>
                {isActive ? downIcon : rightIcon}
                <span className='header'>{sectionName}</span>
              </CollapseButton>
              {additionalSwitch}
              {additionalSwitchText}
              <Switch
                defaultChecked
                size='small'
                className='toggle-switch'
                style={leftToggle ? { marginLeft: 'auto' } : {}}
                onChange={() => this.onToggleClick(toggleSection)}
              />
              <div className='padding-left-text'>
                <span>
                  <FormattedMessage
                    defaultMessage='Show diff only'
                    description='Toggle text that determines whether to show diff only in the model
                      comparison page'
                  />
                </span>
              </div>
            </div>
          </th>
        </tr>
      </tbody>
    );
  }

  renderParams() {
    return (
      <tbody className='scrollable-table'>
        {this.renderDataRows(
          this.props.paramLists,
          <FormattedMessage
            defaultMessage='Parameters'
            description='Field name text for parameters table in the model comparison page'
          />,
          this.state.paramsActive,
          this.state.paramsToggle,
        )}
      </tbody>
    );
  }

  renderSchemaSectionHeader(activeSection, sectionName) {
    const { runInfos } = this.props;
    const { schemaActive } = this.state;
    const isActive = this.state[activeSection];
    const { minusIcon, plusIcon } = this.icons;
    return (
      <tbody>
        {
          <tr className={`${schemaActive ? '' : 'hidden-row'}`}>
            <th
              scope='rowgroup'
              className='schema-table-header block-content'
              colSpan={runInfos.length + 1}
            >
              <button
                className='schema-collapse-button'
                onClick={() => this.onToggleClick(activeSection)}
              >
                {isActive ? minusIcon : plusIcon}
                <strong style={{ paddingLeft: 4 }}>{sectionName}</strong>
              </button>
            </th>
          </tr>
        }
      </tbody>
    );
  }

  renderSchema(activeSection, sectionName, listByIndex, listByName) {
    const { schemaActive, compareByColumnNameToggle, schemaToggle } = this.state;
    const isActive = this.state[activeSection];
    const showSchemaSection = schemaActive && isActive;
    const showListByIndex = !compareByColumnNameToggle && !_.isEmpty(listByIndex);
    const showListByName = compareByColumnNameToggle && !_.isEmpty(listByName);
    const listByIndexHeaderMap = (key, data) => (
      <>
        {sectionName} [{key}]
      </>
    );
    const listByNameHeaderMap = (key, data) => key;
    const schemaFormatter = (value) => value;
    const schemaFieldName = (
      <FormattedMessage
        defaultMessage='Schema {sectionName}'
        description='Field name text for schema table in the model comparison page'
        values={{ sectionName: sectionName }}
      />
    );
    return (
      <tbody className='scrollable-table schema-scrollable-table'>
        {this.renderDataRows(
          listByIndex,
          schemaFieldName,
          showSchemaSection && showListByIndex,
          schemaToggle,
          listByIndexHeaderMap,
          schemaFormatter,
        )}
        {this.renderDataRows(
          listByName,
          schemaFieldName,
          showSchemaSection && showListByName,
          schemaToggle,
          listByNameHeaderMap,
          schemaFormatter,
        )}
      </tbody>
    );
  }

  renderMetrics() {
    const { runInfos, metricLists } = this.props;
    const { metricActive, metricToggle } = this.state;
    const { chartIcon } = this.icons;
    const metricsHeaderMap = (key, data) => {
      return (
        <Link
          to={Routes.getMetricPageRoute(
            runInfos.map((info) => info.run_uuid).filter((uuid, idx) => data[idx] !== undefined),
            key,
            // TODO: Refactor so that the breadcrumb
            // on the linked page is for model registry
            [runInfos[0].experiment_id],
          )}
          target='_blank'
          title='Plot chart'
        >
          {key}
          {chartIcon}
        </Link>
      );
    };
    return (
      <tbody className='scrollable-table'>
        {this.renderDataRows(
          metricLists,
          <FormattedMessage
            defaultMessage='Metrics'
            description='Field name text for metrics table in the model comparison page'
          />,
          metricActive,
          metricToggle,
          metricsHeaderMap,
          Utils.formatMetric,
        )}
      </tbody>
    );
  }

  // eslint-disable-next-line no-unused-vars
  renderDataRows(
    list,
    fieldName,
    show = true,
    toggle = false,
    headerMap = (key, data) => key,
    formatter = (value) => (isNaN(value) ? `"${value}"` : value),
  ) {
    const keys = CompareRunUtil.getKeys(list);
    const data = {};
    keys.forEach((k) => (data[k] = []));
    list.forEach((records, i) => {
      keys.forEach((k) => data[k].push(undefined));
      records.forEach((r) => (data[r.key][i] = r.value));
    });
    if (_.isEmpty(keys) || _.isEmpty(list)) {
      return (
        <tr className={`table-row ${show ? '' : 'hidden-row'}`}>
          <th scope='row' className='rowHeader block-content'>
            <CenteredText>
              <FormattedMessage
                defaultMessage='{fieldName} are empty'
                description='Default text in data table where items are empty in the model
                  comparison page'
                values={{ fieldName: fieldName }}
              />
            </CenteredText>
          </th>
        </tr>
      );
    }
    const isAllNumeric = _.every(keys, (key) => !isNaN(key));
    if (isAllNumeric) {
      keys.sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
    } else {
      keys.sort();
    }
    let identical = true;
    const resultRows = keys.map((k) => {
      const isDifferent = data[k].length > 1 && _.uniq(data[k]).length > 1;
      identical = !isDifferent && identical;
      return (
        <tr
          key={k}
          className={`table-row ${(toggle && !isDifferent) || !show ? 'hidden-row' : ''}`}
        >
          <th scope='row' className='rowHeader block-content'>
            {headerMap(k, data[k])}
          </th>
          {data[k].map((value, i) => (
            <td
              className={`data-value block-content ${isDifferent ? 'highlight-data' : ''}`}
              key={this.props.runInfos[i].getRunUuid()}
            >
              <span className='truncate-text single-line cell-content'>
                {value === undefined ? '-' : formatter(value)}
              </span>
            </td>
          ))}
        </tr>
      );
    });
    if (identical && toggle) {
      return (
        <tr className={`table-row ${show ? '' : 'hidden-row'}`}>
          <th scope='row' className='rowHeader block-content'>
            <CenteredText>
              <FormattedMessage
                defaultMessage='{fieldName} are identical'
                // eslint-disable-next-line max-len
                description='Default text in data table where items are identical in the model comparison page'
                values={{ fieldName: fieldName }}
              />
            </CenteredText>
          </th>
        </tr>
      );
    }
    return resultRows;
  }
}

const getModelVersionSchemaColumnsByIndex = (columns) => {
  const columnsByIndex = {};
  columns.forEach((column, index) => {
    const name = column.name ? column.name : '';
    const type = column.type ? column.type : '';
    columnsByIndex[index] = {
      key: index,
      value: name !== '' && type !== '' ? `${name}: ${type}` : `${name}${type}`,
    };
  });
  return columnsByIndex;
};

const getModelVersionSchemaColumnsByName = (columns) => {
  const columnsByName = {};
  columns.forEach((column) => {
    const name = column.name ? column.name : '-';
    const type = column.type ? column.type : '-';
    columnsByName[name] = {
      key: name,
      value: type,
    };
  });
  return columnsByName;
};

const mapStateToProps = (state, ownProps) => {
  const runInfos = [];
  const runInfosValid = [];
  const metricLists = [];
  const paramLists = [];
  const runNames = [];
  const runDisplayNames = [];
  const runUuids = [];
  const { modelName, versionsToRuns } = ownProps;
  const inputsListByName = [];
  const inputsListByIndex = [];
  const outputsListByName = [];
  const outputsListByIndex = [];
  for (const modelVersion in versionsToRuns) {
    if (versionsToRuns && modelVersion in versionsToRuns) {
      const runUuid = versionsToRuns[modelVersion];
      const runInfo = getRunInfo(runUuid, state);
      if (runInfo) {
        runInfos.push(runInfo);
        runInfosValid.push(true);
        metricLists.push(Object.values(getLatestMetrics(runUuid, state)));
        paramLists.push(Object.values(getParams(runUuid, state)));
        const runTags = getRunTags(runUuid, state);
        runNames.push(Utils.getRunName(runTags));
        // the following are used to render plots - we only include valid run IDs here
        runDisplayNames.push(Utils.getRunDisplayName(runTags, runUuid));
        runUuids.push(runUuid);
      } else {
        if (runUuid) {
          runInfos.push(RunInfo.fromJs({ run_uuid: runUuid }));
        } else {
          runInfos.push(RunInfo.fromJs({ run_uuid: 'None' }));
        }
        runInfosValid.push(false);
        metricLists.push([]);
        paramLists.push([]);
        runNames.push('Invalid Run');
      }
      const schema = getModelVersionSchemas(state, modelName, modelVersion);
      inputsListByIndex.push(Object.values(getModelVersionSchemaColumnsByIndex(schema.inputs)));
      inputsListByName.push(Object.values(getModelVersionSchemaColumnsByName(schema.inputs)));
      outputsListByIndex.push(Object.values(getModelVersionSchemaColumnsByIndex(schema.outputs)));
      outputsListByName.push(Object.values(getModelVersionSchemaColumnsByName(schema.outputs)));
    }
  }

  return {
    runInfos,
    runInfosValid,
    metricLists,
    paramLists,
    runNames,
    runDisplayNames,
    runUuids,
    modelName,
    inputsListByName,
    inputsListByIndex,
    outputsListByName,
    outputsListByIndex,
  };
};

const DEFAULT_COLUMN_WIDTH = 200;

const styles = {
  wrapper: (numRuns) => ({
    '.compare-table': {
      // 1 extra unit for header column
      minWidth: (numRuns + 1) * DEFAULT_COLUMN_WIDTH,
    },
  }),
  compareModelVersionsView: {
    'button:focus': {
      outline: 'none',
      boxShadow: 'none',
    },
    'td.block-content th.block-content': {
      whiteSpace: 'nowrap',
      textOverflow: 'ellipsis',
      tableLayout: 'fixed',
      boxSizing: 'content-box',
    },
    'th.schema-table-header': {
      height: 28,
      padding: 0,
    },
    'tr.table-row': {
      display: 'table',
      width: '100%',
      tableLayout: 'fixed',
    },
    'tr.hidden-row': {
      display: 'none',
    },
    'tbody.scrollable-table': {
      width: '100%',
      display: 'block',
      border: 'none',
      maxHeight: 400,
      overflowY: 'auto',
    },
    'tbody.schema-scrollable-table': {
      maxHeight: 200,
    },
    '.switch-button-container': {
      display: 'flex',
      paddingTop: 16,
      paddingBottom: 16,
    },
    'button.schema-collapse-button': {
      textAlign: 'left',
      display: 'block',
      width: '100%',
      height: '100%',
      border: 'none',
    },
    '.collapse-button': {
      textAlign: 'left',
      display: 'flex',
      alignItems: 'center',
      border: 'none',
      backgroundColor: 'white',
      paddingLeft: 0,
    },
    '.cell-content': {
      maxWidth: '200px',
      minWidth: '100px',
    },
    '.padding-left-text': {
      paddingLeft: 8,
    },
    '.padding-right-text': {
      paddingRight: 16,
    },
    '.toggle-switch': {
      marginTop: 2,
    },
    '.header': {
      paddingLeft: 8,
      fontSize: 16,
    },
  },
};

export const CompareModelVersionsView = connect(mapStateToProps)(CompareModelVersionsViewImpl);
