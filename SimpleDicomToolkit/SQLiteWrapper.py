"""
Created on Tue Sep  5 16:54:20 2017

@author: HeyDude
"""

from SimpleDicomToolkit import Logger
import sqlite3 as lite
import logging

class SQLiteWrapper(Logger):
    """ Pythonic interface for a sqlite3 database """

    DATABASE_FILE = 'database.db'
    ID          = 'id'
    IN_MEMORY   = ':memory:'

    # Datatypes supported by SQLite3
    NULL        = 'NULL'
    TEXT        = 'TEXT'
    REAL        = 'REAL'
    INTEGER     = 'INTEGER'
    BLOB        = 'BLOB'

    _LOG_LEVEL   = logging.ERROR


    def __init__(self, database_file=None):
        """ Connect to database and create tables
        database:   new or existing database file
        table_name:     names for table(s) that will be used. If they don't
                        exist they will be created."""

        self.in_memory=False

        if database_file is None:
            database_file = self.DATABASE_FILE
        elif database_file == SQLiteWrapper.IN_MEMORY:
            self.in_memory=True

        self.database_file = database_file
        self.connected = False # self.connect() needs this attribute
        self.connection = None # Databse connection
        self.cursor = None # Database cursor

        self.close()


    def execute(self, sql_query, values=None, close=True, fetch_all=False, debug=False):
        """ Execute a sql query, database connection is opened when not
        already connected. Connection  will be closed based on the close flag.
        If fetch_all is True, all results are fetched from query.
        """

        self.connect()

        self.logger.debug(sql_query)
        try:
            if values is None:
                result = self.cursor.execute(sql_query)
            else:
                result = self.cursor.execute(sql_query, values)
        except:
            self.logger.error('Could not excute query: \n %s', sql_query)
            self.logger.error('Wiht values: \n %s', values)
            raise

        if fetch_all:
            result = result.fetchall()
        if close:
            self.close()

        return result

    def add_columns(self, table_name, column_names, var_type=None,
                    close=True):
        """ Add columns to a table """

        # keep correspondence
        var_type = dict(zip(column_names, var_type))

        # remove existing columns
        column_names = set(column_names)
        column_names = column_names.difference(self.column_names(table_name))

        if not column_names:
            return

        for name in column_names:
            self.add_column(table_name, name, var_type=var_type[name],
                            close=False, skip_if_exist=False)

        if close:
            self.close()


    def add_column(self, table_name, column_name, var_type=None,
                   close=True):
        """ Add columns to a table. New columns will be created,
        existing columns will be ignored."""

        if var_type is None:
            var_type = self.TEXT

        cmd = 'ALTER table {table_name} ADD COLUMN {column_name} {var_type}'

        #if not column_name in self.column_names(table_name):

        self.execute(cmd.format(column_name=column_name,
                                table_name=table_name,
                                var_type=var_type), close=False)
        if close:
            self.close()

    def rename_table(self, source_name, destination_name, close=True):
        """ Rename Table """

        cmd = 'ALTER TABLE {source_name} RENAME TO {destination_name}'
        self.execute(cmd.format(source_name=source_name,
                                 destination_name=destination_name),
                                 close=close)

    def delete_column(self, table_name, column_name, close=True):
        """ Delete column from table """

        if not column_name in self.column_names(table_name):
            if close:
                self.close
            return

        TEMP_TABLE = 'dummy'
        keep_columns = self.column_names(table_name)
        keep_columns.remove(column_name)
        # keep_columns.remove(self.ID)

        cmd  = ('CREATE TABLE {temp_table} AS SELECT {place_holder}'
                ' FROM {table_name}')

        place_holder = ''
        for name in keep_columns:
            place_holder += name + ', '
        place_holder = place_holder[:-2]
        try:
            self.execute(cmd .format(place_holder = place_holder,
                                     temp_table=TEMP_TABLE,
                                     table_name=table_name),
                                     close=False)
        except:
            self.delete_table(TEMP_TABLE)
            raise

        self.delete_table(table_name, close=False)
        self.rename_table(TEMP_TABLE, table_name, close=False)

        if close:
            self.close()

    def delete_table(self,  table_name, close=False):
        """ Delete table """
        if table_name not in self.table_names:
            return
        else:
            cmd = 'DROP TABLE IF EXISTS {table_name}'.format(table_name=table_name)
            self.execute(cmd, close=close)

    def create_table(self, table_name, close=True):
        """ Create a table to the database """
        cmd = ('CREATE TABLE IF NOT EXISTS {table} '
               '({col_id} INTEGER AUTO_INCREMENT PRIMARY KEY)')

        cmd = cmd.format(table=table_name, col_id=self.ID)
        self.execute(cmd, close=close)


    def get_column(self, table_name, column_name, 
                   close=True, sort=True, distinct=True):
        """ Return column values from table """

        if distinct:
            distinct = 'DISTINCT'
        else:
            distinct = ''

        cmd = 'SELECT {distinct} {column} FROM {table}'
        if sort:
            cmd += ' ORDER BY {column}'
        cmd = cmd.format(column=column_name, table=table_name, distinct=distinct)
        result = self.execute(cmd, close=close, fetch_all=True)

        result = [res[0] for res in result]

        if close:
            self.close()
        return result

    def query(self, source_table, destination_table = None, column_names=None,
               close=True, sort_by=None, partial_match=False, **kwargs):
        """ Perform a query on a table. E.g.:
            database.query(city = 'Rotterdam',
                           street = 'Blaak') returns all rows where column
            city has value 'Rotterdam' and column street has value 'Blaak'

            columns specifies which columns will be returned.
        """
        if column_names is None:
            # if columns are None assume values for every column are passes
            column_str = '*'
        else:
            column_str = SQLiteWrapper.list_to_string(column_names)

        query = 'SELECT {columns} FROM {source_table} WHERE '

        query = query.format(source_table=source_table, columns=column_str)

        if destination_table is not None:
            self.delete_table(destination_table)
            query = 'CREATE TABLE {destination_table} AS ' + query
            query = query.format(destination_table=destination_table)

        # append multiple conditions
        for col_name in kwargs.keys():
            if not partial_match:
                query += '{col_name}=? AND '.format(col_name=col_name)
            else:
                query += '{col_name} LIKE ? AND '.format(col_name=col_name)

        query = query[:-4]  # remove last AND from string

        if sort_by is not None:
            query += ' ORDER BY {0}'.format(sort_by)

        values = list(kwargs.values())

        if partial_match:
            values = ['%{}%'.format(value) for value in values]

        result = self.execute(query, values=values, fetch_all=True, close=close)

        return result


    def insert_list(self, table_name, values, column_names=None, close=True):
        """ Insert a  list with values as a SINGLE row. Each value
        must correspond to a column name in column_names. If column_names
        is None, each value must correspond to a column in the table.

        values = (val1, val2, ..)
        columns = (col1, col2, ..)
        """
        cmd = 'INSERT INTO {table_name}({column_names}) VALUES'


#        if column_names is None:
#            column_names = self.column_names(table_name)
#        if len(column_names) > 1 and len(values) != len(column_names):
#            raise IndexError('Number of values must match number of columns!')
        if not isinstance(values, (list, tuple)):
            values = [values]
        if not isinstance(column_names, (list, tuple)):
            column_names = [column_names]


        cmd = cmd.format(column_names=SQLiteWrapper.list_to_string(column_names),
                         table_name=table_name)
        if isinstance(values, (tuple,list)):
            cmd += SQLiteWrapper.binding_str(len(values))
        else:
            cmd += SQLiteWrapper.binding_str(1)

        self.execute(cmd, values=values, close = close)

    def insert_lists(self, table_name, values, column_names=None, close=True):
        """ Insert a  list with values as multiple rows. Each value in a row
        must correspond to a column name in column_names. If column_names
        is None, each value must correspond to a column in the table.

        values = ((val1, val2,..),(val3, val4, ..))
        columns = (col1, col2, ..)
        """

        for value in values:
            self.insert_list(table_name, value, column_names=column_names, close=False)

        self.close(close)


    def insert_row_dict(self, table_name, data_dict, close=True):
        """ Insert a dictionary in the table. Dictionary must be as follows:
            datadict = {city: ['Rotterdam, 'Amsterdam',..],
                        streets: ['Blaak', 'Kalverstraat,..],
                        ....}
        """
        columns = list(data_dict.keys())
        values = list(data_dict.values())

        self.insert_list(table_name, values, column_names=columns, close=close)

    def delete_rows(self, table_name, column=None, value=None, close=True):
        """ Delete rows from table where column value equals specified value """

        cmd = "DELETE FROM {table} WHERE {column}=?"
        cmd = cmd.format(table=table_name, column=column)

        self.execute(cmd, values=[value], close=close)

    def connect(self):
        """Connect to the SQLite3 database."""

        if not self.connected:
            try:
                self.connection = lite.connect(self.database_file)
            except lite.OperationalError:
                self.logger.error('Could not connect to {0}'.format(self.database_file))
                raise
            self.cursor = self.connection.cursor()
            self.connected = True
            if self._LOG_LEVEL == logging.DEBUG:
                self.connection.set_trace_callback(print)

    def close(self, close = True):
        """Dicconnect form the SQLite3 database and commit changes."""

        if not close:
            return

        if self.connected:
            msg = '\n\n !!! Closing database connection and committing changes. !!!\n\n'
            self.logger.debug(msg)

            # traceback.print_stack()

            self.connection.commit()

            if self.database_file != self.IN_MEMORY:
                # in memory database will caese to exist upon close
                self.connection.close()
                self.connecion = None
                self.cursor = None
                self.connected = False


    def pragma(self, table_name, close=True):
        cmd = 'PRAGMA TABLE_INFO({table_name})'.format(table_name=table_name)
        result = self.execute(cmd, fetch_all=True)
        self.close(close)
        return result

    def column_names(self, table_name, close=True):
        pragma = self.pragma(table_name)
        column_names = [pi[1] for pi in pragma]
        self.close(close)
        return column_names

    @property
    def table_names(self):
        cmd = "SELECT name FROM sqlite_master WHERE type='table';"
        if not self.connection:
            close = True
        else:
            close = False
        result = self.execute(cmd, fetch_all=True, close=close)
        return [ri[0] for ri in result]

    @staticmethod
    def list_to_string(list1):
        # convert list to str "val1, val2, val3 withoud [ or ]
        list_str = ''
        for li in list1:
            list_str += str(li) + ', '
        # remove trailing ,
        list_str = list_str[:-2]
        return list_str

    @staticmethod
    def binding_str(number):
        """ Convert list of numbers to a SQL required format in str """
        binding_str = '('
        for _ in range(0, number):
            binding_str += '?,'
        binding_str = binding_str[:-1] # remove trailing ,
        binding_str += ')'
        return binding_str

