# -*- coding: utf-8 -*-
from PyQt4 import QtGui, QtCore
import random
from PyQt4.QtCore import QVariant
from PyQt4.QtGui import QDialogButtonBox
from qgis.core import QgsField, QgsMapLayerRegistry, QgsMapLayer, \
    QgsVectorJoinInfo
from globals import DOUBLE_FIELD_TYPE_NAME, DEBUG, NUMERIC_FIELD_TYPES, \
    SUM_BASED_COMBINATIONS, MUL_BASED_COMBINATIONS, TEXTUAL_FIELD_TYPES
from process_layer import ProcessLayer
from ui.ui_calculate_iri import Ui_CalculateIRIDialog
from utils import LayerEditingManager, reload_attrib_cbx, reload_layers_in_cbx


class CalculateIRIDialog(QtGui.QDialog, Ui_CalculateIRIDialog):

    def __init__(self, iface, current_layer, project_definition, parent=None):
        QtGui.QDialog.__init__(self, parent)
        self.iface = iface
        self.parent = parent
        self.current_layer = current_layer
        self.project_definition = project_definition
        self.setupUi(self)
        self.ok_button = self.buttonBox.button(QDialogButtonBox.Ok)
        self.calculate_iri = self.calculate_iri_check.isChecked()

        reload_layers_in_cbx(self.aal_layer, QgsMapLayer.VectorLayer)
        reload_attrib_cbx(self.svi_id_field, self.current_layer,
                          NUMERIC_FIELD_TYPES, TEXTUAL_FIELD_TYPES)

    def calculate(self):
        """
        add an SVI attribute to the current layer
        """

        indicators_combination = self.indicators_combination_type.currentText()
        themes_combination = self.themes_combination_type.currentText()

        themes = self.project_definition['children'][1]['children']
        svi_attr_name = 'SVI'
        svi_field = QgsField(svi_attr_name, QVariant.Double)
        svi_field.setTypeName(DOUBLE_FIELD_TYPE_NAME)
        attr_names = ProcessLayer(self.current_layer).add_attributes(
            [svi_field])

        # get the id of the new attribute
        svi_attr_id = ProcessLayer(self.current_layer).find_attribute_id(
            attr_names[svi_attr_name])

        with LayerEditingManager(self.current_layer, 'Add SVI', DEBUG):
            for feat in self.current_layer.getFeatures():
                feat_id = feat.id()

                # init svi_value to the correct value depending on
                # themes_combination
                if themes_combination in SUM_BASED_COMBINATIONS:
                    svi_value = 0
                elif themes_combination in MUL_BASED_COMBINATIONS:
                    svi_value = 1

                # iterate all themes of SVI
                for theme in themes:
                    indicators = theme['children']

                    # init theme_result to the correct value depending on
                    # indicators_combination
                    if indicators_combination in SUM_BASED_COMBINATIONS:
                        theme_result = 0
                    elif indicators_combination in MUL_BASED_COMBINATIONS:
                        theme_result = 1

                    # iterate all indicators of a theme
                    for indicator in indicators:
                        indicator_weighted = (feat[indicator['field']] *
                                              indicator['weight'])
                        if indicators_combination in SUM_BASED_COMBINATIONS:
                            theme_result += indicator_weighted
                        elif indicators_combination in MUL_BASED_COMBINATIONS:
                            theme_result *= indicator_weighted
                    if indicators_combination == 'Average':
                        theme_result /= len(indicators)

                    # combine the indicators of each theme
                    theme_weighted = theme_result * theme['weight']
                    if themes_combination in SUM_BASED_COMBINATIONS:
                            svi_value += theme_weighted
                    elif themes_combination in MUL_BASED_COMBINATIONS:
                        svi_value *= theme_weighted
                if themes_combination == 'Average':
                    svi_value /= len(themes)

                self.current_layer.changeAttributeValue(
                    feat_id, svi_attr_id, svi_value)

        if self.calculate_iri_check:
            self._calculateIRI(svi_attr_id)

    def _calculateIRI(self, svi_attr_id):
        """
        Copy the AAL and calculate an IRI attribute to the current layer
        """

        aal_weight = self.project_definition['children'][0]['weight']
        svi_weight = self.project_definition['children'][1]['weight']

        iri_combination = self.iri_combination_type.currentText()

        iri_attr_name = 'IRI'
        iri_field = QgsField(iri_attr_name, QVariant.Double)
        iri_field.setTypeName(DOUBLE_FIELD_TYPE_NAME)
        copy_aal_attr_name = 'AAL'
        aal_field = QgsField(copy_aal_attr_name, QVariant.Double)
        aal_field.setTypeName(DOUBLE_FIELD_TYPE_NAME)

        attr_names = ProcessLayer(self.current_layer).add_attributes(
            [aal_field, iri_field])

        # get the id of the new attributes
        iri_attr_id = ProcessLayer(self.current_layer).find_attribute_id(
            attr_names[iri_attr_name])
        copy_aal_attr_id = ProcessLayer(self.current_layer).find_attribute_id(
            attr_names[copy_aal_attr_name])

        join_layer = QgsMapLayerRegistry.instance().mapLayersByName(self.aal_layer.currentText())[0]
        join_info = QgsVectorJoinInfo()
        join_info.joinLayerId = join_layer.id()
        join_info.joinFieldName = self.aal_id_field.currentText()
        join_info.targetFieldName = self.svi_id_field.currentText()
        self.current_layer.addJoin(join_info)

        aal_attr_name = '%s_%s' % (self.aal_layer.currentText(), self.aal_field.currentText())

        with LayerEditingManager(self.current_layer, 'Add IRI', DEBUG):
            for feat in self.current_layer.getFeatures():
                feat_id = feat.id()
                svi_value = feat.attributes()[svi_attr_id]
                aal_value = feat[aal_attr_name]

                if iri_combination == 'Sum':
                    iri_value = svi_value * svi_weight + aal_value * aal_weight
                elif iri_combination == 'Multiplication':
                    iri_value = svi_value * svi_weight * aal_value * aal_weight
                elif iri_combination == 'Average':
                    iri_value = (svi_value * svi_weight +
                                 aal_value * aal_weight) / 2.0

                # copy AAL
                self.current_layer.changeAttributeValue(
                    feat_id, copy_aal_attr_id, aal_value)
                # store IRI
                self.current_layer.changeAttributeValue(
                    feat_id, iri_attr_id, iri_value)

        self.current_layer.removeJoin(join_info.joinLayerId)

    def on_calculate_iri_check_toggled(self, on):
        self.calculate_iri = on
        if self.calculate_iri:
            self.check_iri_fields()
        else:
            self.ok_button.setEnabled(True)

    def on_aal_field_currentIndexChanged(self, index):
        self.check_iri_fields()

    def on_aal_layer_currentIndexChanged(self, index):
        selected_layer = QgsMapLayerRegistry.instance().mapLayers().values()[
            self.aal_layer.currentIndex()]
        reload_attrib_cbx(self.aal_field, selected_layer, NUMERIC_FIELD_TYPES)
        reload_attrib_cbx(self.aal_id_field, selected_layer,
                          NUMERIC_FIELD_TYPES, TEXTUAL_FIELD_TYPES)
        self.check_iri_fields()

    def check_iri_fields(self):
        valid_state = False
        if (self.aal_field.currentText() and self.aal_layer.currentText()
            and self.aal_id_field and self.svi_id_field):
            valid_state = True
        self.ok_button.setEnabled(valid_state)