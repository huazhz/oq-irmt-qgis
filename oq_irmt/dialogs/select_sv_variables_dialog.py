# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Irmt
                                 A QGIS plugin
 OpenQuake Integrated Risk Modelling Toolkit
                              -------------------
        begin                : 2013-10-24
        copyright            : (C) 2014 by GEM Foundation
        email                : devops@openquake.org
 ***************************************************************************/

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
from PyQt4.QtCore import pyqtSlot
from PyQt4.QtGui import (QDialog,
                         QDialogButtonBox)

from oq_irmt.ui.ui_select_sv_variables import Ui_SelectSvVariablesDialog
from oq_irmt.utilities.utils import WaitCursorManager, SvNetworkError


class SelectSvVariablesDialog(QDialog):
    """
    Modal dialog giving to the user the possibility to select
    social vulnerability variables to import from the oq-platform
    """
    def __init__(self, downloader):
        QDialog.__init__(self)
        # Set up the user interface from Designer.
        self.ui = Ui_SelectSvVariablesDialog()
        self.ui.setupUi(self)
        self.ok_button = self.ui.buttonBox.button(QDialogButtonBox.Ok)
        self.set_ok_button()
        # login to platform, to be able to retrieve sv indices
        self.sv_downloader = downloader
        self.indicators_info_dict = {}
        with WaitCursorManager():
            self.fill_studies()
            self.fill_themes()
        self.ui.indicator_multiselect.unselected_widget.itemClicked.connect(
            self.update_indicator_info)
        self.ui.indicator_multiselect.selected_widget.itemClicked.connect(
            self.update_indicator_info)
        self.ui.indicator_multiselect.selection_changed.connect(
            self.set_ok_button)
        self.ui.zone_multiselect.selection_changed.connect(
            self.set_ok_button)

    @pyqtSlot(str)
    def on_theme_cbx_currentIndexChanged(self):
        theme = self.ui.theme_cbx.currentText()
        with WaitCursorManager():
            self.fill_subthemes(theme)

    @pyqtSlot()
    def on_filter_btn_clicked(self):
        with WaitCursorManager():
            self.fill_indicators()

    @pyqtSlot(str)
    def on_study_cbx_currentIndexChanged(self):
        with WaitCursorManager():
            self.fill_zones()
            self.fill_indicators()
            admin_levels = self.sv_downloader.get_admin_levels_for_study(
                self.ui.study_cbx.currentText())
            if not any(int(level) > 0 for level in admin_levels):
                self.ui.country_multiselect.hide()
            else:
                self.ui.country_multiselect.show()

    def set_ok_button(self):
        self.ok_button.setEnabled(
            self.ui.indicator_multiselect.selected_widget.count() > 0
            and self.ui.zone_multiselect.selected_widget.count() > 0)

    def fill_studies(self):
        try:
            studies = self.sv_downloader.get_studies()
            self.ui.study_cbx.addItems(studies)
        except SvNetworkError as e:
            raise SvNetworkError(
                "Unable to download social vulnerability studies: %s" % e)

    def fill_themes(self):
        self.ui.theme_cbx.clear()
        # load list of themes from the platform
        self.ui.theme_cbx.addItems([None])
        try:
            themes = self.sv_downloader.get_themes()
            self.ui.theme_cbx.addItems(themes)
        except SvNetworkError as e:
            raise SvNetworkError(
                "Unable to download social vulnerability themes: %s" % e)
        # populate the subsequent combo boxes accordingly with the currently
        # selected item
        current_theme = self.ui.theme_cbx.currentText()
        self.fill_subthemes(current_theme)

    def fill_subthemes(self, theme):
        self.ui.subtheme_cbx.clear()
        # load list of subthemes from the platform
        self.ui.subtheme_cbx.addItems([None])
        if theme:
            try:
                subthemes = self.sv_downloader.get_subthemes_by_theme(theme)
                self.ui.subtheme_cbx.addItems(subthemes)
            except SvNetworkError as e:
                raise SvNetworkError(
                    "Unable to download social vulnerability"
                    " subthemes: %s" % e)

    def fill_indicators(self):
        self.ui.indicator_multiselect.set_unselected_items([])
        # load list of social vulnerability variable names from the platform
        name_filter = self.ui.name_filter_le.text()
        keywords = self.ui.keywords_le.text()
        theme = self.ui.theme_cbx.currentText()
        subtheme = self.ui.subtheme_cbx.currentText()
        study = self.ui.study_cbx.currentText()
        try:
            filter_result_dict = self.sv_downloader.get_indicators_info(
                name_filter, keywords, theme, subtheme, study)
            self.indicators_info_dict.update(filter_result_dict)
            names = sorted(
                [code + ': ' + filter_result_dict[code]['name']
                    for code in filter_result_dict])
            self.ui.indicator_multiselect.add_unselected_items(names)
        except SvNetworkError as e:
            raise SvNetworkError(
                "Unable to download social vulnerability names: %s" % e)

    def update_indicator_info(self, item):
        hint_text = item.text()
        indicator_code = item.text().split(':')[0]
        indicator_info_dict = self.indicators_info_dict[indicator_code]
        hint_text += '\n\n' + 'Description:\n' + indicator_info_dict[
            'description']
        self.ui.indicator_details.setText(hint_text)

    def fill_zones(self):
        # load from platform a list of zones belonging to the selected study
        study_name = self.ui.study_cbx.currentText()
        try:
            zones_dict = self.sv_downloader.get_zones_info(study_name)
            names = sorted(
                [zones_dict[iso] + ' (' + iso + ')'
                    for iso in zones_dict])
            self.ui.zone_multiselect.set_unselected_items(names)
        except SvNetworkError as e:
            raise SvNetworkError(
                "Unable to download the list of zones: %s" % e)