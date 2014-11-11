# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Svir
                                 A QGIS plugin
 OpenQuake Social Vulnerability and Integrated Risk
                              -------------------
        begin                : 2013-10-24
        copyright            : (C) 2013 by GEM Foundation
        email                : devops@openquake.org
 ***************************************************************************/

# Copyright (c) 2010-2013, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake.  If not, see <http://www.gnu.org/licenses/>.
"""
from PyQt4.QtCore import QVariant
from qgis import QPyNullVariant
from qgis.core import QgsField
from qgis.gui import QgsMessageBar
from globals import (DOUBLE_FIELD_TYPE_NAME, DEBUG, SUM_BASED_OPERATORS,
                     MUL_BASED_OPERATORS, DEFAULT_OPERATOR, OPERATORS_DICT)
from process_layer import ProcessLayer
from utils import LayerEditingManager, tr, toggle_select_features_widget


def calculate_svi(iface, current_layer, project_definition):
    """
    add an SVI attribute to the current layer
    """

    svi_node = project_definition['children'][1]
    themes = svi_node['children']
    try:
        themes_operator = svi_node['operator']
    except KeyError:
        themes_operator = DEFAULT_OPERATOR

    if 'svi_field' in project_definition:
        svi_attr_name = project_definition['svi_field']
        if DEBUG:
            print 'Reusing %s for SVI' % svi_attr_name
    else:
        svi_attr_name = 'SVI'
        svi_field = QgsField(svi_attr_name, QVariant.Double)
        svi_field.setTypeName(DOUBLE_FIELD_TYPE_NAME)
        attr_names = ProcessLayer(current_layer).add_attributes(
            [svi_field])
        svi_attr_name = attr_names[svi_attr_name]

    # get the id of the new attribute
    svi_attr_id = ProcessLayer(current_layer).find_attribute_id(svi_attr_name)

    discarded_feats_ids = []
    try:
        with LayerEditingManager(current_layer, 'Add SVI', DEBUG):
            for feat in current_layer.getFeatures():
                # If a feature contains any NULL value, discard_feat will
                # be set to True and the corresponding SVI will be set to
                # NULL
                discard_feat = False
                feat_id = feat.id()

                # init svi_value to the correct value depending on
                # themes_operator
                if themes_operator in SUM_BASED_OPERATORS:
                    svi_value = 0
                elif themes_operator in MUL_BASED_OPERATORS:
                    svi_value = 1

                # iterate all themes of SVI
                for theme in themes:
                    indicators = theme['children']

                    #set default operator
                    try:
                        indicators_operator = theme['operator']
                    except KeyError:
                        indicators_operator = DEFAULT_OPERATOR
                    # init theme_result to the correct value depending on
                    # indicators_operator
                    if indicators_operator in SUM_BASED_OPERATORS:
                        theme_result = 0
                    elif indicators_operator in MUL_BASED_OPERATORS:
                        theme_result = 1

                    # iterate all indicators of a theme
                    for indicator in indicators:
                        if (feat[indicator['field']] ==
                                QPyNullVariant(float)):
                            discard_feat = True
                            discarded_feats_ids.append(feat_id)
                            break
                        # For "Average (equal weights)" it's equivalent to use
                        # equal weights, or to sum the indicators
                        # (all weights 1)
                        # and divide by the number of indicators (we use
                        # the latter solution)
                        if indicators_operator in (OPERATORS_DICT['SUM_S'],
                                                   OPERATORS_DICT['AVG'],
                                                   OPERATORS_DICT['MUL_S']):
                            indicator_weighted = feat[indicator['field']]
                        else:
                            indicator_weighted = (feat[indicator['field']] *
                                                  indicator['weight'])

                        if indicators_operator in \
                                SUM_BASED_OPERATORS:
                            theme_result += indicator_weighted
                        elif indicators_operator in \
                                MUL_BASED_OPERATORS:
                            theme_result *= indicator_weighted
                        else:
                            error_message = (
                                'invalid indicators_operator: %s' %
                                indicators_operator)
                            raise RuntimeError(error_message)
                    if discard_feat:
                        break
                    if indicators_operator == OPERATORS_DICT['AVG']:
                        theme_result /= len(indicators)

                    # combine the indicators of each theme
                    # For "Average (equal weights)" it's equivalent to use
                    # equal weights, or to sum the themes (all weights 1)
                    # and divide by the number of themes (we use
                    # the latter solution)
                    if themes_operator in (OPERATORS_DICT['SUM_S'],
                                           OPERATORS_DICT['AVG'],
                                           OPERATORS_DICT['MUL_S']):
                        theme_weighted = theme_result
                    else:
                        theme_weighted = theme_result * theme['weight']

                    if themes_operator in SUM_BASED_OPERATORS:
                        svi_value += theme_weighted
                    elif themes_operator in MUL_BASED_OPERATORS:
                        svi_value *= theme_weighted
                if discard_feat:
                    svi_value = QPyNullVariant(float)
                else:
                    if themes_operator == OPERATORS_DICT['AVG']:
                        svi_value /= len(themes)

                current_layer.changeAttributeValue(
                    feat_id, svi_attr_id, svi_value)
        msg = ('The SVI has been calculated for fields containing '
               'non-NULL values and it was added to the layer as '
               'a new attribute called %s') % svi_attr_name
        iface.messageBar().pushMessage(
            tr('Info'), tr(msg), level=QgsMessageBar.INFO)
        if discarded_feats_ids:
            widget = toggle_select_features_widget(
                tr('Warning'),
                tr('Invalid indicators were found in some features while '
                   'calculating SVI'),
                tr('Select invalid features'),
                current_layer,
                discarded_feats_ids,
                current_layer.selectedFeaturesIds())
            iface.messageBar().pushWidget(widget, QgsMessageBar.WARNING)

        project_definition['svi_field'] = svi_attr_name
        return svi_attr_id, discarded_feats_ids

    except TypeError as e:
        current_layer.dataProvider().deleteAttributes([svi_attr_id])
        msg = 'Could not calculate SVI due to data problems: %s' % e
        iface.messageBar().pushMessage(tr('Error'), tr(msg),
                                       level=QgsMessageBar.CRITICAL)


def calculate_iri(iface, current_layer, project_definition, svi_attr_id,
                  risk_field_name, discarded_feats_ids, iri_operator=None,
                  reuse_field=False):
    """
    Copy the RISK and calculate an IRI attribute to the current layer
    :param reuse_field:
    """

    #set default
    if iri_operator is None:
        iri_operator = DEFAULT_OPERATOR

    risk_weight = project_definition['children'][0]['weight']
    svi_weight = project_definition['children'][1]['weight']

    if 'iri_field' in project_definition:
        iri_attr_name = project_definition['iri_field']
        if DEBUG:
            print 'Reusing %s for IRI' % iri_attr_name
    else:
        iri_attr_name = 'IRI'
        iri_field = QgsField(iri_attr_name, QVariant.Double)
        iri_field.setTypeName(DOUBLE_FIELD_TYPE_NAME)
        attr_names = ProcessLayer(current_layer).add_attributes([iri_field])
        iri_attr_name = attr_names[iri_attr_name]

    # get the id of the new attributes
    iri_attr_id = ProcessLayer(current_layer).find_attribute_id(iri_attr_name)

    discarded_risk_feats_ids = []

    try:
        with LayerEditingManager(current_layer, 'Add IRI', DEBUG):
            for feat in current_layer.getFeatures():
                feat_id = feat.id()
                svi_value = feat.attributes()[svi_attr_id]
                risk_value = feat[risk_field_name]
                if (risk_value == QPyNullVariant(float)
                        or feat_id in discarded_feats_ids):
                    iri_value = QPyNullVariant(float)
                    discarded_risk_feats_ids.append(feat_id)
                elif iri_operator == OPERATORS_DICT['SUM_S']:
                    iri_value = svi_value + risk_value
                elif iri_operator == OPERATORS_DICT['MUL_S']:
                    iri_value = svi_value * risk_value
                elif iri_operator == OPERATORS_DICT['SUM_W']:
                    iri_value = (
                        svi_value * svi_weight + risk_value * risk_weight)
                elif iri_operator == OPERATORS_DICT['MUL_W']:
                    iri_value = (
                        svi_value * svi_weight * risk_value * risk_weight)
                elif iri_operator == OPERATORS_DICT['AVG']:
                    # For "Average (equal weights)" it's equivalent to use
                    # equal weights, or to sum the indices (all weights 1)
                    # and divide by the number of indices (we use
                    # the latter solution)
                    iri_value = (svi_value + risk_value) / 2.0
                # store IRI
                current_layer.changeAttributeValue(
                    feat_id, iri_attr_id, iri_value)
        project_definition['operator'] = iri_operator
        # set the field name for the copied RISK layer
        project_definition['risk_field'] = risk_field_name
        project_definition['iri_field'] = iri_attr_name
        msg = ('The IRI has been calculated for fields containing '
               'non-NULL values and it was added to the layer as '
               'a new attribute called %s') % iri_attr_name
        iface.messageBar().pushMessage(tr('Info'), tr(msg),
                                       level=QgsMessageBar.INFO)
        widget = toggle_select_features_widget(
            tr('Warning'),
            tr('Invalid values were found in some features while calculating '
               'IRI'),
            tr('Select invalid features'),
            current_layer,
            discarded_risk_feats_ids,
            current_layer.selectedFeaturesIds())
        iface.messageBar().pushWidget(widget, QgsMessageBar.WARNING)
        return iri_attr_id

    except TypeError as e:
        current_layer.dataProvider().deleteAttributes(
            [iri_attr_id])
        msg = 'Could not calculate IRI due to data problems: %s' % e

        iface.messageBar().pushMessage(tr('Error'), tr(msg),
                                       level=QgsMessageBar.CRITICAL)
