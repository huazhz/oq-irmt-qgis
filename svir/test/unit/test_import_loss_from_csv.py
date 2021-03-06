# -*- coding: utf-8 -*-
# /***************************************************************************
# Irmt
#                                 A QGIS plugin
# OpenQuake Integrated Risk Modelling Toolkit
#                              -------------------
#        begin                : 2013-10-24
#        copyright            : (C) 2015 by GEM Foundation
#        email                : devops@openquake.org
# ***************************************************************************/
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

# import qgis libs so that we set the correct sip api version

import unittest
import os.path
import tempfile
from collections import namedtuple
from qgis.core import QgsVectorLayer
from svir.test.utilities import get_qgis_app
from svir.calculations.process_layer import ProcessLayer
from svir.dialogs.select_input_layers_dialog import SelectInputLayersDialog

QGIS_APP, CANVAS, IFACE, PARENT = get_qgis_app()


class ImportLossFromCsvTestCase(unittest.TestCase):

    def test_import_loss_from_dummy_csv(self):
        curr_dir_name = os.path.dirname(__file__)
        data_dir_name = os.path.join(
            curr_dir_name, os.pardir, 'data', 'loss', 'dummy')
        csv_file_path = os.path.join(
            data_dir_name, 'dummy_loss_data.csv')
        dest_shp_file_path = os.path.join(
            data_dir_name, 'output', 'dummy_loss_layer.shp')

        dlg = SelectInputLayersDialog(IFACE)
        shp_layer = dlg.import_loss_layer_from_csv(csv_file_path,
                                                   dest_shp_file_path,
                                                   delete_lon_lat=True)
        expected_field_names = ('PT_ID', 'AAL', 'DEATH')
        Feature = namedtuple('Feature', expected_field_names)
        expected_rows = [Feature('A', 32, 5),
                         Feature('B', 14, 7),
                         Feature('C', 10, 3),
                         Feature('D', 16, 4)]
        actual_field_names = tuple(
            field.name() for field in shp_layer.fields())
        self.assertEqual(actual_field_names, expected_field_names)
        for i, feat in enumerate(shp_layer.getFeatures()):
            actual_row = Feature(*feat.attributes())
            self.assertEqual(actual_row, expected_rows[i])

    def test_import_loss_from_csv_exported_by_oqengine(self):
        curr_dir_name = os.path.dirname(__file__)
        data_dir_name = os.path.join(
            curr_dir_name, os.pardir, 'data', 'loss', 'from_oqengine')
        csv_file_path = os.path.join(
            data_dir_name, 'output-161-avg_losses-rlz-000_61.csv')
        out_dir = tempfile.gettempdir()
        dest_shp_file_path = os.path.join(
            out_dir, 'loss_layer.shp')
        dlg = SelectInputLayersDialog(IFACE)
        shp_layer = dlg.import_loss_layer_from_csv(csv_file_path,
                                                   dest_shp_file_path)
        expected_layer_path = os.path.join(
            data_dir_name, 'expected_layer.shp')
        expected_layer = QgsVectorLayer(
            expected_layer_path, 'expected_layer', 'ogr')
        res = ProcessLayer(shp_layer).has_same_content_as(expected_layer)
        self.assertEqual(
            res, True, msg='Please check the content of the imported layer')
