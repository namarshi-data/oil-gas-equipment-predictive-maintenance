using System.Text.Json;
using Microsoft.AnalysisServices.Tabular;

if (args.Length < 1) throw new ArgumentException("Usage: ModelValidator <TMDL definition folder> [output model JSON]");
var db = TmdlSerializer.DeserializeDatabaseFromFolder(Path.GetFullPath(args[0]));
var result = new {
    parser = "Microsoft.AnalysisServices.Tabular.TmdlSerializer",
    packageVersion = "19.114.8",
    tmdlParsed = true,
    tables = db.Model.Tables.Count,
    measures = db.Model.Tables.Sum(t => t.Measures.Count),
    relationships = db.Model.Relationships.Count,
    roles = db.Model.Roles.Select(r => r.Name).ToArray(),
    daxExecuted = false,
    powerBIDesktopRefreshed = false
};
if (args.Length>1) File.WriteAllText(args[1],Microsoft.AnalysisServices.Tabular.JsonSerializer.SerializeDatabase(db));
Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(result,new JsonSerializerOptions{WriteIndented=true}));
